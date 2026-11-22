"""Browser acceptance for React, FastAPI, PostgreSQL and a separate worker."""
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

origin = os.environ.get("WORKBENCH_TEST_ORIGIN", "http://127.0.0.1:8001")
evidence = os.environ.get("WORKBENCH_SCREENSHOTS")


def capture(page, name):
    if evidence:
        path = Path(evidence)
        path.mkdir(exist_ok=True, parents=True)
        page.screenshot(path=path / f"{name}.png", full_page=True, animations="disabled")


def publish(page, date, expected):
    page.get_by_label("Snapshot date").select_option(date)
    page.get_by_role("button", name="Load sample holdings").click()
    expect(page.get_by_role("heading", name="Check imported holdings")).to_be_visible()
    page.get_by_role("button", name="Confirm and value holdings").click()
    expect(page.get_by_text("Review published.", exact=True)).to_be_visible(timeout=15_000)
    expect(page.get_by_text(expected, exact=True)).to_be_visible()


def tab(page, name):
    page.get_by_role("navigation", name="Workspace views").get_by_role("button", name=name, exact=True).click()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=os.environ.get("WORKBENCH_CHROMIUM"))
    page = browser.new_page(viewport={"width": 1240, "height": 960}, accept_downloads=True)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(origin)
    page.get_by_role("button", name="Start sample workspace").click()
    tab(page, "Monitor")
    page.get_by_label("Holding", exact=True).select_option("XNAS:AAPL")
    page.get_by_label("Portfolio weight (%)").fill("50.5")
    page.get_by_role("button", name="Add concentration rule").click()
    expect(page.get_by_text("Concentration rule saved.")).to_be_visible()
    tab(page, "Review")
    publish(page, "2026-11-13", "$3,000.00")
    tab(page, "Monitor")
    page.get_by_label("Refresh date").select_option("2026-11-20")
    page.get_by_role("button", name="Queue refresh").click()
    expect(page.get_by_text("$3,040.00", exact=True)).to_be_visible(timeout=15_000)
    expect(page.get_by_text("+$40.00", exact=True)).to_be_visible()
    expect(page.get_by_text("+$150.00", exact=True)).to_be_visible()
    expect(page.get_by_text("-$110.00", exact=True)).to_be_visible()
    expect(page.get_by_text("Holdings confirmed for 13 Nov 2026.")).to_be_visible()
    page.get_by_label("Scenario holding").select_option("XNAS:AAPL")
    page.get_by_role("button", name="Calculate scenario").click()
    expect(page.get_by_text("$2,886.00", exact=True)).to_be_visible()
    capture(page, "01-aud-review-and-scenario")
    with page.expect_download() as download:
        page.get_by_role("link", name="Download review evidence (JSON)").click()
    assert download.value.suggested_filename == "portfolio-review-2026-11-20.json"

    tab(page, "Monitor")
    expect(page.get_by_text("XNAS:AAPL crossed 50.5%", exact=True)).to_be_visible()
    capture(page, "02-monitor-and-alert")
    page.get_by_role("button", name="Mark as read").click()
    expect(page.get_by_text("Read", exact=True)).to_be_visible()

    tab(page, "NewsAlpha")
    expect(page.get_by_text("Illustrative reporting calendar update")).to_be_visible()
    page.get_by_label("Include PPO research presets").check()
    page.get_by_role("button", name="Run sample experiment").click()
    expect(page.get_by_role("rowheader", name="PPO price + news (seed 19)")).to_be_visible(timeout=15_000)
    cash = page.get_by_role("row", name="Cash 0.00% 0.00%")
    expect(cash).to_be_visible()
    capture(page, "03-holdings-events-and-strategies")

    report_id = page.request.get(origin + "/api/workbench/v1/reviews").json()[0]["id"]
    page.reload()
    expect(page.get_by_text("$3,040.00", exact=True)).to_be_visible()
    publish(page, "2026-11-27", "$1,520.00")
    expect(page.get_by_text("Partial coverage", exact=True)).to_be_visible()
    expect(page.get_by_text("Covered subtotal (AUD)", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Change since previous review")).to_have_count(0)
    desktop_width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert desktop_width[0] <= desktop_width[1], desktop_width
    page.set_viewport_size({"width": 390, "height": 844})
    mobile_width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert mobile_width[0] <= mobile_width[1], mobile_width
    capture(page, "04-mobile-partial-coverage")

    stranger = browser.new_page()
    stranger.goto(origin)
    stranger.get_by_role("button", name="Start sample workspace").click()
    expect(stranger.get_by_text("No published review yet.")).to_be_visible()
    response = stranger.request.get(origin + "/api/workbench/v1/reviews/" + report_id)
    assert response.status == 404

    tab(page, "Settings")
    capture(page, "05-workspace-settings")
    page.get_by_label("Confirmation", exact=True).fill("DELETE")
    page.get_by_role("button", name="Delete workspace permanently").click()
    expect(page.get_by_text("Workspace deleted.")).to_be_visible()
    expect(page.get_by_role("button", name="Start sample workspace")).to_be_visible()
    assert page.request.get(origin + "/api/workbench/v1/reviews").status == 401
    assert not page_errors, page_errors
    browser.close()

print("Browser passed: imports, refresh, AUD review, scenario, alerts, research, partial coverage and privacy")
