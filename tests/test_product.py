from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os

import pytest

from src.product.valuation import SAMPLE_CSV, aud_review, compare_reviews, parse_holdings


def test_aud_values_and_exact_attribution():
    positions, issues = parse_holdings(SAMPLE_CSV.encode())
    assert not issues
    earlier = aud_review("2026-11-13", positions)
    later = aud_review("2026-11-20", positions)
    assert Decimal(earlier["aud_total"]) == 3000
    assert Decimal(later["aud_total"]) == 3040
    bridge = compare_reviews(earlier, later)
    assert Decimal(bridge["aud_change"]) == 40
    assert {key: Decimal(value) for key, value in bridge["effects"].items()} == {
        "price": 150, "fx": -110, "quantity": 0, "cash": 0,
    }
    changed = aud_review("2026-11-20", [
        {**row, "quantity": "9"} if row["instrument"] == "XNAS:AAPL" else row for row in positions
    ])
    assert Decimal(compare_reviews(earlier, changed)["effects"]["quantity"]) == -154


def test_partial_coverage_and_invalid_csv():
    positions, _ = parse_holdings(SAMPLE_CSV.encode())
    partial = aud_review("2026-11-27", positions)
    assert partial["status"] == "partial"
    assert partial["aud_total"] is None
    assert Decimal(partial["aud_covered_subtotal"]) == 1520
    assert all(row["weight"] is None for row in partial["positions"])
    assert not compare_reviews(aud_review("2026-11-20", positions), partial)["eligible"]
    _, issues = parse_holdings(b"instrument,quantity\nASX:BHP,1\nXNAS:AAPL,-1\nASX:BHP,2\nCASH:AUD,0\n")
    assert len(issues) == 3


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_DATABASE_URL"), reason="Requires a migrated PostgreSQL test database")
def test_postgres_checkpoint():
    from fastapi.testclient import TestClient

    from src.product.api import API, create_app
    from src.product.database import database_engine, scope
    from src.product.service import query
    from src.product.worker import run_one

    engine = database_engine(os.environ["WORKBENCH_TEST_DATABASE_URL"])
    origin = "http://localhost:8001"
    headers = {"Origin": origin}
    app = create_app(engine=engine, origin=origin, demo_enabled=True)

    def preview(client, date, content=SAMPLE_CSV):
        result = client.post(API + "/imports", headers=headers, data={"snapshot_date": date},
                             files={"file": ("sample.csv", content, "text/csv")})
        assert result.status_code == 201, result.text
        return result.json()

    with TestClient(app, base_url=origin) as first, TestClient(app, base_url=origin) as second:
        assert first.get(API + "/reviews").status_code == 401
        assert first.post(API + "/session", headers={"Origin": "https://other.invalid"}).status_code == 403
        owner = first.post(API + "/session", headers=headers).json()["workspace_id"]
        other = second.post(API + "/session", headers=headers).json()["workspace_id"]
        assert owner != other

        invalid = preview(first, "2026-11-13", "instrument,quantity\nASX:BHP,20\n")
        assert invalid["issues"]
        assert first.post(f'{API}/imports/{invalid["id"]}/confirm', headers=headers).status_code == 422
        draft = preview(first, "2026-11-13")
        assert preview(first, "2026-11-13")["id"] == draft["id"]
        confirm = f'{API}/imports/{draft["id"]}/confirm'
        assert second.post(confirm, headers=headers).status_code == 404
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: first.post(confirm, headers=headers), range(2)))
        assert all(result.status_code == 202 for result in results)
        assert len({result.json()["id"] for result in results}) == 1
        job_id = results[0].json()["id"]
        assert first.get(f"{API}/jobs/{job_id}").json()["state"] == "queued"
        assert second.get(f"{API}/jobs/{job_id}").status_code == 404

        with ThreadPoolExecutor(max_workers=2) as executor:
            claimed = list(executor.map(lambda _: run_one(engine), range(2)))
        assert claimed.count(True) == 1
        report_id = first.get(f"{API}/jobs/{job_id}").json()["report_id"]
        report = first.get(f"{API}/reviews/{report_id}")
        assert Decimal(report.json()["aud_total"]) == 3000
        assert report.headers["Cache-Control"] == "no-store"
        exported = first.get(f"{API}/reviews/{report_id}/export")
        assert exported.json() == report.json()
        assert 'attachment' in exported.headers["Content-Disposition"]
        assert second.get(f"{API}/reviews/{report_id}/export").status_code == 404
        assert len(first.get(API + "/reviews").json()) == 1
        assert second.get(f"{API}/reviews/{report_id}").status_code == 404
        cookies = dict(first.cookies)

        with engine.begin() as conn:
            assert not query(conn, "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user").scalar_one()
            scope(conn, other)
            assert query(conn, "SELECT id FROM product_reports WHERE id = :id", id=report_id).first() is None
        with engine.begin() as conn:
            assert query(conn, "SELECT id FROM product_reports WHERE id = :id", id=report_id).first() is None

        with TestClient(create_app(engine=engine, origin=origin, demo_enabled=True), base_url=origin) as restarted:
            restarted.cookies.update(cookies)
            assert restarted.get(f"{API}/reviews/{report_id}").status_code == 200
            assert restarted.delete(API + "/session", headers=headers).status_code == 204
        assert first.get(f"{API}/reviews/{report_id}").status_code == 401
    engine.dispose()
