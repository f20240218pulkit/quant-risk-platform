from pathlib import Path
from playwright.sync_api import sync_playwright, expect
import json
import os

directory = Path(os.getenv("WORKBENCH_SCREENSHOTS", "workbench-screenshots")).resolve()
directory.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    page = browser.new_page(viewport={"width": 1450, "height": 960}, accept_downloads=True)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:8767", wait_until="domcontentloaded")
    page.get_by_role("button", name="Preview sample").click(timeout=30000)
    page.get_by_role("button", name="Confirm and run review").click()
    expect(page.get_by_text("95% historical VaR", exact=True)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download review", exact=True).click()
    review = json.loads(download.value.path().read_text())
    assert review["source"] == "synthetic demo" and len(review["replay"]) == 260
    page.screenshot(path=directory / "portfolio-review.png")
    page.get_by_role("tab", name="Simulation & optimisation", exact=True).click()
    page.get_by_role("button", name="Run simulation and optimisation").click()
    expect(page.get_by_text("Simulated 95% VaR", exact=True)).to_be_visible(timeout=20000)
    page.get_by_text("Save to workspace", exact=True).click()
    page.get_by_role("button", name="Save review", exact=True).click()
    expect(page.get_by_text("Review saved for this browser session.")).to_be_visible()
    page.get_by_role("link", name="Saved reviews & alerts").click()
    expect(page.get_by_role("button", name="Download saved review")).to_be_visible()
    page.get_by_role("tab", name="Threshold alerts").click()
    page.get_by_role("button", name="Add alert").click()
    expect(page.get_by_text("Rule saved.")).to_be_visible()
    page.get_by_role("link", name="Strategy research").click()
    page.get_by_text("Include experimental PPO (two seeds)").click()
    page.get_by_role("button", name="Run research comparison").click()
    expect(page.get_by_text("Net return difference from adding sentiment")).to_be_visible(timeout=30000)
    with page.expect_download() as download:
        page.get_by_role("button", name="Download experiment").click()
    report = json.loads(download.value.path().read_text())
    assert len(report["runs"]) == 10 and len(report["cost_sensitivity"]) == 3
    assert any(run["ledger"] for run in report["runs"].values())
    page.screenshot(path=directory / "strategy-research.png")
    page.get_by_role("link", name="AUD and USD analysis").click()
    page.get_by_role("button", name="Analyse currency exposure").click()
    expect(page.get_by_text("Portfolio value", exact=True)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download FX review").click()
    fx = json.loads(download.value.path().read_text())
    assert fx["base"] == "AUD" and "Cash USD" in fx["values"]
    page.get_by_role("link", name="Broker import").click()
    page.get_by_role("button", name="Load sample broker holdings").click()
    expect(page.get_by_role("button", name="Download broker holdings CSV")).to_be_visible()
    page.get_by_role("button", name="Use broker holdings in a review").click()
    page.get_by_role("button", name="Preview imported holdings").click()
    page.get_by_role("button", name="Confirm and run review").click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Download review", exact=True).click()
    imported = json.loads(download.value.path().read_text())
    assert imported["holdings"]["source"] == "broker"
    assert not errors, errors
    print(f"Browser passed all five pages. Review {review['valuation']['total_value']} USD, {len(report['runs'])} strategies, FX {fx['total']} AUD.")
    browser.close()
