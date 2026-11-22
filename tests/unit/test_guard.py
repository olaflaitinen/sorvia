from __future__ import annotations

import pytest

from sorvia.guard import GuardPolicy, SqlRejected, check_sql

POLICY = GuardPolicy.from_relations(
    ["pharma.sale", "pharma.sale_item", "pharma.branch", "pharma.drug", "pharma.customer",
     "pharma.v_sale_lines", "analytics.fact_sales", "analytics.dim_date"],
    max_rows=100,
)


def ok(sql: str) -> str:
    return check_sql(sql, POLICY).sql


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("DELETE FROM pharma.sale", "not_a_query"),
        ("UPDATE pharma.drug SET unit_price = 1", "not_a_query"),
        ("INSERT INTO pharma.branch VALUES (1)", "not_a_query"),
        ("DROP TABLE pharma.sale", "not_a_query"),
        ("TRUNCATE pharma.sale", "not_a_query"),
        ("GRANT sorvia_app TO sorvia_nl", "not_a_query"),
        ("COPY pharma.drug TO PROGRAM 'x'", "not_a_query"),
        ("SELECT 1; DROP TABLE pharma.sale", "multiple_statements"),
        ("SELECT * INTO t FROM pharma.sale", "forbidden_construct"),
        ("SELECT * FROM pharma.sale FOR UPDATE", "forbidden_construct"),
        ("WITH d AS (DELETE FROM pharma.sale RETURNING *) SELECT * FROM d", "forbidden_construct"),
        ("SELECT pg_sleep(10)", "function_not_allowed"),
        ("SELECT set_config('role', 'x', false)", "function_not_allowed"),
        ("SELECT current_setting('data_directory')", "function_not_allowed"),
        ("SELECT dblink('x', 'y')", "function_not_allowed"),
        ("SELECT sorvia.redeem_scope_ticket(NULL)", "function_not_allowed"),
        ("SELECT * FROM pg_catalog.pg_authid", "system_object"),
        ("SELECT * FROM pg_stat_activity", "system_object"),
        ("SELECT * FROM information_schema.tables", "system_object"),
        ("SELECT * FROM sorvia.app_user", "schema_not_allowed"),
        ("SELECT * FROM audit.change_log", "schema_not_allowed"),
        ("SELECT * FROM pharma.sale_default", "unknown_relation"),
        ("SELECT * FROM secret_table", "unknown_relation"),
        ("SELECT * FROM otherdb.pharma.sale", "cross_database"),
        ("SELECT * FROM pharma.sale LIMIT ALL", "invalid_limit"),
        ("", "empty"),
        ("SELEC 1", "parse_error"),
    ],
)
def test_rejections(sql: str, code: str) -> None:
    with pytest.raises(SqlRejected) as info:
        check_sql(sql, POLICY)
    assert info.value.code == code


def test_limit_is_added() -> None:
    assert ok("SELECT sale_id FROM pharma.sale").endswith("LIMIT 100")


def test_limit_is_capped() -> None:
    assert ok("SELECT sale_id FROM pharma.sale LIMIT 100000").endswith("LIMIT 100")


def test_small_limit_is_kept() -> None:
    result = check_sql("SELECT sale_id FROM pharma.sale LIMIT 5", POLICY)
    assert result.sql.endswith("LIMIT 5")
    assert not result.limit_applied


def test_unqualified_relations_are_qualified() -> None:
    result = check_sql("SELECT count(*) FROM sale s JOIN branch b USING (branch_id)", POLICY)
    assert "pharma.sale" in result.sql and "pharma.branch" in result.sql
    assert result.relations == ("pharma.branch", "pharma.sale")


def test_ctes_and_set_operations() -> None:
    sql = ("WITH m AS (SELECT branch_id, count(*) AS n FROM pharma.sale GROUP BY branch_id) "
           "SELECT branch_id FROM m UNION SELECT branch_id FROM pharma.branch")
    assert "LIMIT 100" in ok(sql)


def test_window_and_aggregate_functions_are_allowed() -> None:
    ok("SELECT branch_id, rank() OVER (ORDER BY sum(net_amount) DESC), "
       "percentile_cont(0.5) WITHIN GROUP (ORDER BY net_amount), date_trunc('month', sold_at), "
       "to_char(sold_at, 'YYYY'), string_agg(DISTINCT branch_id::text, ',') FROM pharma.sale GROUP BY 1, 4, 5")


def test_domain_functions_are_allowed() -> None:
    ok("SELECT pharma.business_date(sold_at) FROM pharma.sale")
    ok("SELECT * FROM pharma.batch_location_at(5, now())")


def test_comments_are_stripped() -> None:
    assert "--" not in ok("SELECT 1 AS x -- ; DROP TABLE pharma.sale")


def test_join_limit() -> None:
    joins = " ".join(f"JOIN pharma.branch b{i} ON b{i}.branch_id = s.branch_id" for i in range(13))
    with pytest.raises(SqlRejected) as info:
        check_sql(f"SELECT 1 FROM pharma.sale s {joins}", POLICY)
    assert info.value.code == "too_complex"


def test_too_long() -> None:
    with pytest.raises(SqlRejected) as info:
        check_sql("SELECT " + "1 + " * 5000 + "1", POLICY)
    assert info.value.code == "too_long"
