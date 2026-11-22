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


def test_approved_observations_pin_cutoffs_and_event_evidence(tmp_path, monkeypatch):
    from src.product.market import configured_market, holding_events

    path = tmp_path / "approved.json"
    path.write_text("""{
      "source":"Allowed fixture","revision":"2026-11-20.1",
      "listings":{"XNAS:AAPL":{"currency":"USD","label":"Apple"}},
      "periods":{"2026-11-20":{"cutoff":"2026-11-20T23:00:00Z",
         "prices":{"XNAS:AAPL":{"value":"110","observed_at":"2026-11-20T22:00:00Z","available_at":"2026-11-20T22:00:00Z"}},
         "aud_per_usd":{"value":"1.40","observed_at":"2026-11-20T22:00:00Z","available_at":"2026-11-20T22:00:00Z"}}},
      "events":[
         {"id":"eligible","instrument":"XNAS:AAPL","title":"Earnings","category":"Announcement",
          "available_at":"2026-11-20T23:00:00Z","url":"https://example.com/earnings"},
         {"id":"late","instrument":"XNAS:AAPL","title":"Later","category":"Announcement",
          "available_at":"2026-11-21T00:00:00Z","url":"https://example.com/later"}
      ]
    }""")
    monkeypatch.setenv("WORKBENCH_APPROVED_MARKET_FILE", str(path))
    monkeypatch.delenv("WORKBENCH_APPROVED_DATA", raising=False)
    with pytest.raises(RuntimeError, match="entitlement"):
        configured_market(False)
    monkeypatch.setenv("WORKBENCH_APPROVED_DATA", "1")
    market = configured_market(False)
    positions = [{"instrument": "XNAS:AAPL", "quantity": "10"}]
    report = aud_review("2026-11-20", positions, **market.review_inputs("2026-11-20"))
    assert Decimal(report["aud_total"]) == 1540
    assert report["revision"] == "2026-11-20.1"
    assert report["positions"][0]["close_observed_at"].startswith("2026-11-20T22:00")
    assert [item["id"] for item in holding_events(report, market)] == ["eligible"]
    path.write_text(path.read_text().replace("2026-11-20T22:00:00Z", "2026-11-21T22:00:00Z"))
    with pytest.raises(ValueError, match="report cutoff"):
        configured_market(False)


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_DATABASE_URL"), reason="Requires a migrated PostgreSQL test database")
def test_followup_workflows_and_reclaimed_job():
    from datetime import date

    from fastapi.testclient import TestClient

    from src.product.api import API, create_app
    from src.product.database import database_engine
    from src.product.worker import claim, finish, run_one
    from src.product.workflows import plan_refreshes

    engine = database_engine(os.environ["WORKBENCH_TEST_DATABASE_URL"])
    origin = "http://localhost:8001"
    with TestClient(create_app(engine=engine, origin=origin, demo_enabled=True),
                    base_url=origin, headers={"Origin": origin}) as client:
        assert client.post(API + "/session").status_code == 201
        rule = client.post(API + "/monitor/rules", json={"instrument": "XNAS:AAPL", "threshold": "50.5"})
        assert rule.status_code == 201, rule.text
        draft = client.post(API + "/imports", data={"snapshot_date": "2026-11-13"}, files={"file": SAMPLE_CSV})
        assert draft.status_code == 201
        confirm = client.post(API + "/imports/" + draft.json()["id"] + "/confirm")
        assert confirm.status_code == 202
        abandoned = claim(engine, lease_seconds=0)
        replacement = claim(engine)
        assert abandoned["id"] == replacement["id"]
        assert abandoned["lease_token"] != replacement["lease_token"]
        assert not finish(engine, abandoned, None)
        positions, _ = parse_holdings(SAMPLE_CSV.encode())
        assert finish(engine, replacement, aud_review("2026-11-13", positions))
        assert not client.get(API + "/monitor").json()["alerts"]

        assert client.put(API + "/monitor/schedule", json={"enabled": True}).status_code == 200
        plan_refreshes(engine, date(2026, 11, 20))
        assert run_one(engine)
        assert not run_one(engine)
        recent = client.get(API + "/reviews").json()[0]["id"]
        report = client.get(API + "/reviews/" + recent).json()
        assert report["snapshot_date"] == "2026-11-20"
        assert report["holdings_date"] == "2026-11-13"
        assert Decimal(report["aud_total"]) == 3040
        alerts = client.get(API + "/monitor").json()["alerts"]
        assert len(alerts) == 1
        assert alerts[0]["acknowledged_at"] is None
        assert client.put(API + "/monitor/alerts/" + alerts[0]["id"] + "/read").status_code == 204
        assert client.get(API + "/monitor").json()["alerts"][0]["acknowledged_at"]

        p = client.post(API + "/reviews/" + recent + "/scenario",
                        json={"instrument": "XNAS:AAPL", "change_percent": "-10"})
        assert p.status_code == 200
        assert Decimal(p.json()["scenario_aud"]) == 2886
        assert len(client.get(API + "/reviews/" + recent + "/events").json()["events"]) == 2

        assert client.post(API + "/refresh", json={"snapshot_date": "2026-11-27"}).status_code == 202
        assert run_one(engine)
        latest = client.get(API + "/reviews").json()[0]
        assert latest["status"] == "partial"
        assert len(client.get(API + "/monitor").json()["alerts"]) == 1

        research = client.get(API + "/research?ppo=true")
        assert research.status_code == 200
        assert len(research.json()["runs"]) == 10
        exported = client.get(API + "/workspace/export")
        assert len(exported.json()["reports"]) == 3
        assert client.request("DELETE", API + "/workspace", json={"confirm": "wrong"}).status_code == 422
        cookie = dict(client.cookies)
        assert client.request("DELETE", API + "/workspace", json={"confirm": "DELETE"}).status_code == 204
        client.cookies.update(cookie)
        assert client.get(API + "/reviews").status_code == 401
    engine.dispose()


@pytest.mark.skipif(not os.environ.get("WORKBENCH_TEST_DATABASE_URL"), reason="Requires a migrated PostgreSQL test database")
def test_private_login_callback_with_stubbed_oidc(tmp_path, monkeypatch):
    import time

    from fastapi.responses import RedirectResponse
    from fastapi.testclient import TestClient

    from src.product.api import API, create_app
    from src.product.database import database_engine
    from src.product.identity import OAuth

    file = tmp_path / "approved.json"
    file.write_text("""{"source":"Qualified fixture","revision":"1",
      "listings":{"XNAS:AAPL":{"currency":"USD","label":"Apple"}},
      "periods":{"2024-11-20":{"cutoff":"2024-11-20T23:00:00Z","prices":{}}}}""")
    origin = "https://workbench.test"
    issuer = "https://identity.test/"
    variables = {
        "WORKBENCH_APPROVED_MARKET_FILE": str(file), "WORKBENCH_APPROVED_DATA": "1",
        "WORKBENCH_OIDC_ISSUER": issuer, "WORKBENCH_OIDC_CLIENT_ID": "client",
        "WORKBENCH_OIDC_CLIENT_SECRET": "test-secret", "WORKBENCH_OIDC_STATE_SECRET": "x" * 48,
        "WORKBENCH_OIDC_ALLOWED_SUBJECTS": "invited",
    }
    for key, value in variables.items():
        monkeypatch.setenv(key, value)

    class StubIdentity:
        async def authorize_redirect(self, request, redirect_uri, **kwargs):
            assert redirect_uri == origin + "/auth/callback"
            assert kwargs["prompt"] == "login"
            request.session["stub"] = True
            return RedirectResponse(issuer + "authorize", status_code=302)

        async def authorize_access_token(self, request):
            assert request.session["stub"]
            return {"id_token": "stub-token",
                    "userinfo": {"iss": issuer, "sub": request.query_params["subject"], "auth_time": int(time.time())}}

    def register(_oauth, name, **kwargs):
        assert kwargs["server_metadata_url"] == issuer + ".well-known/openid-configuration"
        assert kwargs["client_kwargs"]["code_challenge_method"] == "S256"
        return StubIdentity()

    monkeypatch.setattr(OAuth, "register", register)
    engine = database_engine(os.environ["WORKBENCH_TEST_DATABASE_URL"])
    with TestClient(create_app(engine=engine, origin=origin, demo_enabled=False),
                    base_url=origin, headers={"Origin": origin}, follow_redirects=False) as client:
        assert client.get(API + "/sample").json()["csv"] is None
        assert client.post(API + "/session").status_code == 404
        assert client.get("/auth/login").status_code == 302
        assert client.get("/auth/callback?subject=uninvited").status_code == 403
        assert client.get(API + "/reviews").status_code == 401
        assert client.get("/auth/login").status_code == 302
        callback = client.get("/auth/callback?subject=invited")
        assert callback.status_code == 303
        assert "HttpOnly" in callback.headers.get_list("set-cookie")[0]
        workspace = client.get(API + "/session").json()["workspace_id"]
        assert client.get(API + "/workspace/export").status_code == 200
        assert client.delete(API + "/session").status_code == 204
        assert client.get("/auth/login").status_code == 302
        assert client.get("/auth/callback?subject=invited").status_code == 303
        assert client.get(API + "/session").json()["workspace_id"] == workspace
    engine.dispose()
