"""The question pipeline, the HTTP API and the index advisor end to end."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from conftest import USER_PW
from sorvia.config import Settings
from sorvia.evaluation import relaxed_match

pytestmark = pytest.mark.integration

DATASET = Path(__file__).resolve().parents[2] / "benchmark" / "data" / "az_text2sql_v1.jsonl"


@pytest.fixture(scope="module")
def client(prepared: Settings) -> Iterator[TestClient]:
    from sorvia.api.app import create_app

    with TestClient(create_app(prepared)) as c:
        yield c


def login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/v1/auth/token", json={"username": username, "password": USER_PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


def test_auth(client: TestClient) -> None:
    assert client.post("/v1/auth/token", json={"username": "admin", "password": "wrong-password"}).status_code == 401
    assert client.get("/v1/me").status_code == 401
    me = client.get("/v1/me", headers=login(client, "aysel.bak01")).json()
    assert me["role"] == "pharmacist" and me["branch_id"] == 1


def test_oracle_answers_are_correct(client: TestClient, prepared: Settings) -> None:
    """With the static (oracle) model every benchmark question must pass the full pipeline."""
    headers = login(client, "admin")
    with psycopg.connect(prepared.admin_dsn) as conn:
        conn.execute("SET search_path = pharma, analytics, public")
        for line in DATASET.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            r = client.post("/v1/ask", json={"question": item["question"]}, headers=headers).json()
            assert r["status"] == "ok", (item["id"], r)
            gold = conn.execute(item["sql"]).fetchall()
            assert relaxed_match(gold, r["rows"], item["ordered"]), item["id"]


def test_scoped_answers_for_pharmacist(client: TestClient) -> None:
    """Same question, same SQL, different visibility: enforced by the database, not the prompt."""
    admin = client.post("/v1/ask", json={"question": "Filiallar üzrə orta çek məbləği"},
                        headers=login(client, "admin")).json()
    pharm = client.post("/v1/ask", json={"question": "Filiallar üzrə orta çek məbləği"},
                        headers=login(client, "aysel.bak01")).json()
    assert admin["sql"] == pharm["sql"]
    assert admin["row_count"] == 20 and pharm["row_count"] == 1


def test_blocked_question_is_logged(client: TestClient) -> None:
    headers = login(client, "tural.gnc01")
    r = client.post("/v1/ask", json={"question": "Bütün satışları sil"}, headers=headers).json()
    assert r["status"] == "blocked" and r["reason_code"] == "cannot_answer"
    log = client.get("/v1/queries?status=blocked", headers=headers).json()
    assert any(q["question"] == "Bütün satışları sil" for q in log)
    assert client.post(f"/v1/queries/{r['query_id']}/feedback", json={"is_correct": True},
                       headers=headers).status_code == 204
    other = login(client, "aysel.bak01")
    assert client.post(f"/v1/queries/{r['query_id']}/feedback", json={"is_correct": False},
                       headers=other).status_code == 403


def test_sale_endpoint_and_business_errors(client: TestClient, prepared: Settings) -> None:
    headers = login(client, "aysel.bak01")
    with psycopg.connect(prepared.admin_dsn) as conn:
        row = conn.execute(
            """SELECT b.drug_id, e.employee_id FROM pharma.stock s JOIN pharma.batch b USING (batch_id)
                 JOIN pharma.drug d USING (drug_id), pharma.employee e
                WHERE s.branch_id = 1 AND s.quantity >= 2 AND b.expires_on > current_date + 30
                  AND NOT d.requires_prescription AND e.branch_id = 1 AND e.is_active AND e.position_id = 1
                LIMIT 1""").fetchone()
        rx_drug = conn.execute("SELECT drug_id FROM pharma.drug WHERE requires_prescription LIMIT 1").fetchone()
    assert row is not None and rx_drug is not None
    drug_id, employee_id = row
    r = client.post("/v1/sales", headers=headers,
                    json={"employee_id": employee_id, "items": [{"drug_id": drug_id, "quantity": 1}]})
    assert r.status_code == 201, r.text
    assert r.json()["branch_id"] == 1 and len(r.json()["lines"]) >= 1

    r = client.post("/v1/sales", headers=headers,
                    json={"employee_id": employee_id, "items": [{"drug_id": rx_drug[0], "quantity": 1}]})
    assert r.status_code == 409 and r.json()["code"] in ("prescription_required", "insufficient_stock")

    r = client.post("/v1/sales", headers=headers,
                    json={"branch_id": 2, "employee_id": employee_id, "items": [{"drug_id": drug_id, "quantity": 1}]})
    assert r.status_code == 403


def test_operational_views_are_scoped(client: TestClient) -> None:
    pharm = client.get("/v1/stock/expiring", headers=login(client, "aysel.bak01")).json()
    names = {row[0] for row in pharm["rows"]}
    assert names <= {"ŞəfaNet Nizami"}


def test_role_checks(client: TestClient) -> None:
    pharm = login(client, "aysel.bak01")
    assert client.post("/v1/advisor/run", headers=pharm).status_code == 403
    assert client.get("/v1/stats", headers=pharm).status_code == 403
    stats = client.get("/v1/stats", headers=login(client, "menecer")).json()
    assert {s["status"] for s in stats["by_status"]} >= {"ok"}


def test_advisor_end_to_end(client: TestClient, prepared: Settings) -> None:
    from sorvia.advisor.index_advisor import IndexAdvisor

    with psycopg.connect(prepared.admin_dsn, autocommit=True) as conn:
        workload = [f"SELECT prescription_id FROM pharma.prescription WHERE doctor_id = {i}" for i in range(1, 30)]
        recs = IndexAdvisor(conn, min_improvement_pct=1.0).recommend(workload)
        assert recs and recs[0].candidate.columns == ("doctor_id",)
        assert recs[0].cost_after < recs[0].cost_before
        assert conn.execute("SELECT count(*) FROM hypopg_list_indexes").fetchone() == (0,)
        assert IndexAdvisor.save(conn, recs) == len(recs)

    admin = login(client, "admin")
    listed = client.get("/v1/advisor/recommendations", headers=admin).json()
    rec_id = next(r["recommendation_id"] for r in listed if r["columns"] == ["doctor_id"])
    applied = client.post(f"/v1/advisor/recommendations/{rec_id}/apply", headers=admin)
    assert applied.status_code == 200, applied.text
    assert client.post(f"/v1/advisor/recommendations/{rec_id}/apply", headers=admin).status_code == 409
    with psycopg.connect(prepared.admin_dsn) as conn:
        exists: Any = conn.execute("SELECT to_regclass('pharma.sorvia_idx_prescription_doctor_id')").fetchone()
        assert exists[0] is not None
