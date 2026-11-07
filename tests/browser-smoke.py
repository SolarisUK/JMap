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
    check(page.locator('.map-regions').get_attribute('visibility') == 'visible', 'Regional heatmap enabled by default')
    check(page.locator('.map-region').count() == 4, 'Real nation boundaries load')
    check(page.locator('.map-markers').get_attribute('display') == 'none', 'Sample markers do not obscure regional data')
    check('21.5% deficit' in page.locator('[data-label-for-region="england"]').text_content(), 'Map labels quantify the annual gap')
    page.locator('#workspace').scroll_into_view_if_needed()
    check(not page.locator('#site-search').is_visible(), 'Sample site filters do not imply filtering official map')
    check('Not assessed' in page.locator('.risk-availability').inner_text(), 'No unsupported shortage score')
    page.locator('#regional-balance').scroll_into_view_if_needed()
    screenshot_dir = Path(tempfile.gettempdir()) / 'jmap-browser-review'
    screenshot_dir.mkdir(exist_ok=True)
    page.locator('#workspace').scroll_into_view_if_needed()
    page.screenshot(path=str(screenshot_dir / 'regional-desktop.png'))
    page.locator('[data-ranking-nation="wales"]').click()
    check(page.locator('#regional-detail-title').inner_text() == 'Wales', 'Nation ranking selects details')
    page.locator('.map-region[data-region-key="scotland"]').focus()
    page.keyboard.press('Enter')
    check(page.locator('#regional-detail-title').inner_text() == 'Scotland', 'Nation polygon keyboard selects details')
    check(page.locator('.map-region[data-region-key="scotland"]').get_attribute('aria-pressed') == 'true', 'Selected nation outlined')
    page.click('[data-heat-metric="demand"]')
    check('265.9 TWh' in page.locator('[data-label-for-region="england"]').text_content(), 'Demand map uses official gross demand')
    page.click('[data-heat-metric="renewable"]')
    check('72.3% renewable' in page.locator('[data-label-for-region="scotland"]').text_content(), 'Renewable map shows actual renewable fraction')
    page.click('[data-heat-metric="balance"]')
    baseline_scotland_fill = page.locator('.map-region[data-region-key="scotland"]').get_attribute('fill')
    page.locator('#regional-balance').scroll_into_view_if_needed()
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
    check('deficit' in page.locator('[data-label-for-region="scotland"]').text_content(), 'Scenario updates map values')
    check(page.locator('.map-region[data-region-key="scotland"]').get_attribute('fill') != baseline_scotland_fill, 'Scenario changes map colour against the same scale')
    check('57.04 TWh' in page.locator('#distribution-insights').inner_text(), 'Baseline insights stay distinct')
    check('demandIncrease=40' in page.url and 'generationReduction=40' in page.url, 'Scenario persists in URL')
    page.click('[data-heat-metric="renewable"]')
    check('54.01 TWh' in page.locator('#regional-detail-facts').inner_text(), 'Renewable map details retain the published baseline')
    check('Official annual data' in page.locator('#regional-analysis-period').text_content(), 'Renewable baseline is labelled official during scenario')
    page.click('[data-heat-metric="balance"]')
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
    check(page.locator('.map-regions').get_attribute('visibility') == 'hidden', 'Site layer hides regional fills')
    page.reload()
    check(page.locator('[data-layer="sites"]').get_attribute('aria-pressed') == 'true', 'Layer restores from URL')

    for width in [1440, 1000, 768, 390, 320]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(100)
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'No page overflow at {width}px')
    page.locator('#regional-balance').scroll_into_view_if_needed()
    page.screenshot(path=str(screenshot_dir / 'annual-mobile.png'))
    check(page.locator('.balance-table-scroll').evaluate('(el) => el.scrollWidth > el.clientWidth'), 'Wide table scrolls within mobile container')
    page.click('[data-layer="heatmap"]')
    for width in [1440, 1000, 768, 390, 320]:
        page.set_viewport_size({'width': width, 'height': 900})
        page.wait_for_timeout(100)
        check(page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), f'No regional page overflow at {width}px')
    page.locator('#map-stage').scroll_into_view_if_needed()
    wales_box = page.locator('[data-label-for-region="wales"]').bounding_box()
    england_box = page.locator('[data-label-for-region="england"]').bounding_box()
    check(wales_box['y'] >= england_box['y'] + england_box['height'], 'Mobile nation labels do not overlap')
    check(page.locator('.map-legend').evaluate('(el) => !el.closest("#map-stage")'), 'Regional legend leaves geography unobscured')
    page.screenshot(path=str(screenshot_dir / 'regional-mobile.png'))
    check(not errors, 'No browser runtime errors: ' + repr(errors))
    print(json.dumps({'result': 'passed', 'checks': 'Annual data, sorting, CSV, scenarios, URL restore, linked map, layers, responsive widths, runtime errors', 'screenshots': str(screenshot_dir)}))
    browser.close()
