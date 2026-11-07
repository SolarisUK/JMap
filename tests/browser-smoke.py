"""Optional UI integration checks: python tests/browser-smoke.py (requires Playwright)."""
import csv
import io
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright


def check(condition, message):
    if not condition:
        raise AssertionError(message)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto((Path(__file__).resolve().parents[1] / "UI/main.html").as_uri())
    page.wait_for_selector('#balance-rows tr')
    check(page.locator('#balance-rows tr').count() == 4, 'Four nations load')
    check(page.locator('#balance-rows tr').first.get_attribute('data-nation') == 'scotland', 'Scotland leads baseline coverage')
    check(page.locator('.map-heatmap').get_attribute('visibility') == 'visible', 'Heatmap enabled by default')
    check('Not assessed' in page.locator('.risk-availability').inner_text(), 'No unsupported shortage score')
    page.locator('#regional-balance').scroll_into_view_if_needed()
    screenshot_dir = Path(tempfile.gettempdir()) / 'jmap-browser-review'
    screenshot_dir.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshot_dir / 'annual-desktop.png'))

    page.select_option('#balance-sort', 'deficit')
    check(page.locator('#balance-rows tr').first.get_attribute('data-nation') == 'england', 'England has largest baseline deficit')
    with page.expect_download() as download_event:
        page.click('#export-balance')
    exported = download_event.value
    exported.save_as(str(screenshot_dir / exported.suggested_filename))
    content = Path(exported.path()).read_text(encoding='utf-8-sig')
    rows = list(csv.reader(io.StringIO(content)))
    heading = next(i for i, row in enumerate(rows) if row and row[0] == 'Nation')
    check(rows[heading + 1][0] == 'England', 'CSV follows selected table order')
    check(abs(float(rows[heading + 1][4]) + 57.04046984948886) < 1e-6, 'CSV deficit matches sourced net imports')

    page.locator('.scenario-controls summary').click()
    page.locator('#demand-change').focus()
    page.keyboard.press('End')
    page.locator('#generation-change').focus()
    page.keyboard.press('End')
    check(page.locator('#demand-change-value').inner_text() == '+40%', 'Demand range keyboard works')
    check(page.locator('#generation-change-value').inner_text() == '−40%', 'Generation range keyboard works')
    check(page.locator('#balance-rows .balance-status').all_inner_texts() == ['Annual deficit'] * 4, 'Stress scenario recomputes every balance')
    check('Scenario' in page.locator('#balance-data-year').inner_text(), 'Scenario clearly labelled')
    check('57.04 TWh' in page.locator('#distribution-insights').inner_text(), 'Baseline insights stay distinct')
    check('demandIncrease=40' in page.url and 'generationReduction=40' in page.url, 'Scenario persists in URL')
    page.reload()
    check(page.locator('#demand-change').input_value() == '40', 'Scenario restores on reload')
    check(page.locator('.scenario-controls').get_attribute('open') is not None, 'Restored scenario controls open')
    page.click('#reset-scenario')
    check('Scenario' not in page.locator('#balance-data-year').inner_text(), 'Reset restores official data')
    check('demandIncrease=' not in page.url and 'generationReduction=' not in page.url, 'Reset clears scenario URL')

    page.locator('[data-nation="scotland"] .nation-explore').click()
    check(page.locator('#region').input_value() == 'scotland', 'Annual nation links focus sample map')
    check(page.locator('#summary-scope').inner_text() == 'Scotland', 'Map scope updates')
    check(page.locator('#balance-rows tr').count() == 4, 'Site filters leave annual data independent')
    page.click('#reset-filters')
    page.click('[data-layer="sites"]')
    check(page.locator('.map-heatmap').get_attribute('visibility') == 'hidden', 'Site layer hides heat')
    page.reload()
    check(page.locator('[data-layer="sites"]').get_attribute('aria-pressed') == 'true', 'Layer restores from URL')

    for width in [1440, 1000, 768, 390, 320]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(100)
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'No page overflow at {width}px')
    page.locator('#regional-balance').scroll_into_view_if_needed()
    page.screenshot(path=str(screenshot_dir / 'annual-mobile.png'))
    check(page.locator('.balance-table-scroll').evaluate('(el) => el.scrollWidth > el.clientWidth'), 'Wide table scrolls within mobile container')
    check(not errors, 'No browser runtime errors: ' + repr(errors))
    print(json.dumps({'result': 'passed', 'checks': 'Annual data, sorting, CSV, scenarios, URL restore, linked map, layers, responsive widths, runtime errors', 'screenshots': str(screenshot_dir)}))
    browser.close()
