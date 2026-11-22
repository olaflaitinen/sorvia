"""Business rules, ledger, temporal queries, security and analytics inside PostgreSQL."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from sorvia.config import Settings

pytestmark = pytest.mark.integration


def one(conn: psycopg.Connection[Any], sql: str, params: Any = None) -> Any:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def employee_of(conn: psycopg.Connection[Any], branch_id: int) -> int:
    return int(one(conn, "SELECT employee_id FROM pharma.employee WHERE branch_id = %s AND is_active "
                         "AND position_id IN (1, 2) LIMIT 1", (branch_id,)))


def fresh_batch(conn: psycopg.Connection[Any], rx: bool, expires: str = "2030-01-01") -> tuple[int, int]:
    drug_id = one(conn, "SELECT drug_id FROM pharma.drug WHERE requires_prescription = %s ORDER BY drug_id LIMIT 1",
                  (rx,))
    batch_id = one(conn, """INSERT INTO pharma.batch (drug_id, lot_number, manufactured_on, expires_on)
                            VALUES (%s, 'T-' || gen_random_uuid(), '2018-01-01', %s) RETURNING batch_id""",
                   (drug_id, expires))
    conn.execute("CALL pharma.receive_batch(1::smallint, %s, 10)", (batch_id,))
    return drug_id, batch_id


def test_migrations_are_idempotent(prepared: Settings) -> None:
    from sorvia.migrate import apply_migrations

    assert apply_migrations(prepared.admin_dsn, prepared.migrations_dir) == []


def test_seed_satisfies_invariants(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    assert one(c, """SELECT count(*) FROM (SELECT branch_id, batch_id, sum(quantity_delta) q
                       FROM pharma.batch_movement GROUP BY 1, 2) m
                   FULL JOIN pharma.stock s USING (branch_id, batch_id)
                  WHERE coalesce(m.q, 0) <> coalesce(s.quantity, 0)""") == 0
    assert one(c, """SELECT count(*) FROM pharma.sale_item si JOIN pharma.batch b USING (batch_id)
                  WHERE b.expires_on < pharma.business_date(si.sold_at)""") == 0
    assert one(c, """SELECT count(*) FROM pharma.sale_item si JOIN pharma.sale s USING (sale_id, sold_at)
                   JOIN pharma.batch b USING (batch_id) JOIN pharma.drug d USING (drug_id)
                  WHERE d.requires_prescription AND s.prescription_id IS NULL""") == 0
    assert one(c, "SELECT count(*) FROM pharma.customer WHERE fin_encrypted IS NULL") == 0


def test_register_sale_fefo_discount_and_ledger(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    drug_id, late = fresh_batch(c, rx=False, expires="2031-01-01")
    early = one(c, """INSERT INTO pharma.batch (drug_id, lot_number, manufactured_on, expires_on)
                     VALUES (%s, 'T-early', '2024-01-01', '2029-06-01') RETURNING batch_id""", (drug_id,))
    c.execute("CALL pharma.receive_batch(1::smallint, %s, 3)", (early,))
    # Isolate the test from seeded stock of the same drug.
    c.execute("""UPDATE pharma.stock SET quantity = 0 WHERE branch_id = 1 AND batch_id IN
                 (SELECT batch_id FROM pharma.batch WHERE drug_id = %s AND batch_id NOT IN (%s, %s))""",
              (drug_id, early, late))
    customer = one(c, "INSERT INTO pharma.customer (first_name, last_name, bonus_points) VALUES ('A', 'B', 600) "
                      "RETURNING customer_id")
    sale_id = one(c, "SELECT pharma.register_sale(1::smallint, %s, %s::jsonb, %s)",
                  (employee_of(c, 1), json.dumps([{"drug_id": drug_id, "quantity": 5}]), customer))
    lines = c.execute("SELECT batch_id, quantity FROM pharma.sale_item WHERE sale_id = %s ORDER BY line_no",
                      (sale_id,)).fetchall()
    assert [(r["batch_id"], r["quantity"]) for r in lines] == [(early, 3), (late, 2)]
    sale = c.execute("SELECT gross_amount, discount_amount FROM pharma.sale WHERE sale_id = %s", (sale_id,)).fetchone()
    assert sale is not None
    assert sale["discount_amount"] == round(sale["gross_amount"] * 5 / 100, 2)   # 500+ points = 5%
    assert one(c, "SELECT count(*) FROM pharma.batch_movement WHERE reason = 'sale' AND reference_id = %s",
               (sale_id,)) == 2


def test_expired_batch_cannot_be_sold(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    _, batch_id = fresh_batch(c, rx=False, expires="2020-01-01")
    sale = c.execute("INSERT INTO pharma.sale (sold_at, branch_id, employee_id) VALUES (now(), 1, %s) "
                     "RETURNING sale_id, sold_at", (employee_of(c, 1),)).fetchone()
    with pytest.raises(psycopg.Error) as info:
        c.execute("INSERT INTO pharma.sale_item (sale_id, sold_at, line_no, batch_id, quantity) "
                  "VALUES (%s, %s, 1, %s, 1)", (sale["sale_id"], sale["sold_at"], batch_id))  # type: ignore[index]
    assert info.value.sqlstate == "SV001"


def test_prescription_drug_requires_prescription(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    drug_id, _ = fresh_batch(c, rx=True)
    with pytest.raises(psycopg.Error) as info:
        c.execute("SELECT pharma.register_sale(1::smallint, %s, %s::jsonb)",
                  (employee_of(c, 1), json.dumps([{"drug_id": drug_id, "quantity": 1}])))
    assert info.value.sqlstate == "SV002"


def test_prescription_is_consumed(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    drug_id, _ = fresh_batch(c, rx=True)
    customer = one(c, "INSERT INTO pharma.customer (first_name, last_name) VALUES ('R', 'X') RETURNING customer_id")
    rx = one(c, "INSERT INTO pharma.prescription (customer_id, doctor_id, issued_on, valid_until) "
                "VALUES (%s, 1, current_date, current_date + 10) RETURNING prescription_id", (customer,))
    c.execute("INSERT INTO pharma.prescription_item (prescription_id, drug_id, quantity) VALUES (%s, %s, 2)",
              (rx, drug_id))
    items = json.dumps([{"drug_id": drug_id, "quantity": 2}])
    c.execute("SELECT pharma.register_sale(1::smallint, %s, %s::jsonb, %s, %s)",
              (employee_of(c, 1), items, customer, rx))
    assert one(c, "SELECT dispensed_quantity FROM pharma.prescription_item WHERE prescription_id = %s", (rx,)) == 2
    with pytest.raises(psycopg.Error) as info:   # nothing left on the prescription
        c.execute("SELECT pharma.register_sale(1::smallint, %s, %s::jsonb, %s, %s)",
                  (employee_of(c, 1), items, customer, rx))
    assert info.value.sqlstate == "SV002"


def test_insufficient_stock(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    drug_id, _ = fresh_batch(c, rx=False)
    with pytest.raises(psycopg.Error) as info:
        c.execute("SELECT pharma.register_sale(1::smallint, %s, %s::jsonb)",
                  (employee_of(c, 1), json.dumps([{"drug_id": drug_id, "quantity": 100000}])))
    assert info.value.sqlstate == "SV003"


def test_ledger_is_immutable(admin_conn: psycopg.Connection[Any]) -> None:
    with pytest.raises(psycopg.Error) as info:
        admin_conn.execute("UPDATE pharma.batch_movement SET quantity_delta = 1 "
                           "WHERE movement_id = (SELECT min(movement_id) FROM pharma.batch_movement)")
    assert info.value.sqlstate == "SV005"


def test_transfer_and_traceability(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    _, batch_id = fresh_batch(c, rx=False)
    before = c.execute("SELECT * FROM pharma.batch_location_at(%s, now())", (batch_id,)).fetchall()
    assert [(r["branch_id"], r["quantity"]) for r in before] == [(1, 10)]
    c.execute("CALL pharma.transfer_stock(1::smallint, 2::smallint, %s, 4, %s)", (batch_id, employee_of(c, 1)))
    c.execute("COMMIT")   # the transfer must be visible at clock time
    after = c.execute("SELECT * FROM pharma.batch_location_at(%s, clock_timestamp())", (batch_id,)).fetchall()
    assert [(r["branch_id"], r["quantity"]) for r in after] == [(1, 6), (2, 4)]
    with pytest.raises(psycopg.Error) as info:
        c.execute("CALL pharma.transfer_stock(1::smallint, 2::smallint, %s, 999, %s)", (batch_id, employee_of(c, 1)))
    assert info.value.sqlstate == "SV003"


def test_audit_log_redacts_personal_data(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    cid = one(c, "INSERT INTO pharma.customer (first_name, last_name, fin_hash) VALUES ('Q', 'W', 'h1') "
                 "RETURNING customer_id")
    c.execute("SELECT set_config('sorvia.app_user', 'tester', true)")
    c.execute("UPDATE pharma.customer SET phone = '+994501234567' WHERE customer_id = %s", (cid,))
    row = c.execute("SELECT new_data, app_user FROM audit.change_log WHERE table_name = 'pharma.customer' "
                    "AND operation = 'UPDATE' ORDER BY change_id DESC LIMIT 1").fetchone()
    assert row is not None
    assert row["app_user"] == "tester"
    assert "fin_hash" not in row["new_data"] and row["new_data"]["phone"] == "+994501234567"


def test_reader_without_ticket_sees_no_scoped_rows(prepared: Settings) -> None:
    with psycopg.connect(prepared.reader_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM pharma.sale").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM pharma.drug").fetchone()[0] > 0  # type: ignore[index]
        for forbidden in ("SELECT * FROM sorvia.session_scope", "SELECT * FROM sorvia.app_user",
                          "SELECT fin_hash FROM pharma.customer", "SELECT * FROM audit.change_log"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(forbidden)
            conn.rollback()


def test_tickets_are_single_use_and_scoped(prepared: Settings) -> None:
    with psycopg.connect(prepared.app_dsn, autocommit=True) as app:
        uid = one(app, "SELECT user_id FROM sorvia.app_user WHERE username = 'aysel.bak01'")
        ticket = one(app, "SELECT sorvia.issue_scope_ticket(%s)", (uid,))
    with psycopg.connect(prepared.reader_dsn) as conn:
        with conn.transaction():
            conn.execute("SELECT sorvia.redeem_scope_ticket(%s)", (ticket,))
            branches = conn.execute("SELECT DISTINCT branch_id FROM pharma.sale").fetchall()
            assert branches == [(1,)]
        # The scope dies with the transaction.
        assert conn.execute("SELECT count(*) FROM pharma.sale").fetchone() == (0,)
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT sorvia.redeem_scope_ticket(%s)", (ticket,))


def test_analytics_matches_oltp(admin_conn: psycopg.Connection[Any]) -> None:
    c = admin_conn
    c.execute("CALL analytics.refresh(true)")
    oltp = one(c, "SELECT sum(quantity * unit_price) FROM pharma.sale_item "
                  "WHERE sold_at <= now() - interval '1 minute'")
    star = one(c, "SELECT sum(gross_amount) FROM analytics.fact_sales")
    assert oltp == star
    net_oltp = one(c, "SELECT sum(net_amount) FROM pharma.sale WHERE sold_at <= now() - interval '1 minute'")
    net_star = one(c, "SELECT sum(net_amount) FROM analytics.fact_sales")
    assert abs(net_oltp - net_star) < 1   # cent-level allocation rounding
