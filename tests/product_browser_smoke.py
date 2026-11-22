"""Browser acceptance for React, FastAPI, PostgreSQL and a separate worker."""
import os

from playwright.sync_api import expect, sync_playwright

origin = os.environ.get("WORKBENCH_TEST_ORIGIN", "http://127.0.0.1:8001")


def publish(page, date, expected):
    page.get_by_label("Snapshot date").select_option(date)
    page.get_by_role("button", name="Load sample holdings").click()
    expect(page.get_by_role("heading", name="Check imported holdings")).to_be_visible()
    page.get_by_role("button", name="Confirm and value holdings").click()
    expect(page.get_by_text("Review published.", exact=True)).to_be_visible(timeout=15_000)
    expect(page.get_by_text(expected, exact=True)).to_be_visible()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=os.environ.get("WORKBENCH_CHROMIUM"))
    page = browser.new_page(viewport={"width": 1200, "height": 900})
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.goto(origin)
    page.get_by_role("button", name="Start sample workspace").click()
    publish(page, "2026-11-13", "$3,000.00")
    publish(page, "2026-11-20", "$3,040.00")
    expect(page.get_by_text("+$40.00", exact=True)).to_be_visible()
    expect(page.get_by_text("+$150.00", exact=True)).to_be_visible()
    expect(page.get_by_text("-$110.00", exact=True)).to_be_visible()
    report_id = page.request.get(origin + "/api/workbench/v1/reviews").json()[0]["id"]
    page.reload()
    expect(page.get_by_text("$3,040.00", exact=True)).to_be_visible()
    publish(page, "2026-11-27", "$1,520.00")
    expect(page.get_by_text("Partial coverage", exact=True)).to_be_visible()
    expect(page.get_by_text("Covered subtotal (AUD)", exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Change since previous review")).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    stranger = browser.new_page()
    stranger.goto(origin)
    stranger.get_by_role("button", name="Start sample workspace").click()
    expect(stranger.get_by_text("No published review yet.")).to_be_visible()
    response = stranger.request.get(origin + "/api/workbench/v1/reviews/" + report_id)
    assert response.status == 404
    assert not page_errors, page_errors
    browser.close()

print("Browser passed: import, valuation, attribution, reload, partial coverage and workspace isolation")
