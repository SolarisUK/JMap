"""Operations integration checks. Start the API first; optionally pass --stub-url."""
import argparse
import csv
import io
import json
import re
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def ready(page):
    page.wait_for_function("!document.querySelector('#play').disabled && document.querySelector('#frame-time').textContent.trim().length > 3", timeout=60000)
    check(not page.locator('#error-banner').is_visible(), 'No data error: ' + page.locator('#error-message').text_content())


def seek(page, value):
    page.locator('#time-step').evaluate('(el,value)=>{el.value=value;el.dispatchEvent(new Event("input",{bubbles:true}))}', value)
    page.wait_for_function('(value)=>document.querySelector("#frame-count").textContent === `${value+1} / 48`', arg=value)
    page.wait_for_timeout(250)


args = argparse.ArgumentParser()
args.add_argument('--base-url', default='http://127.0.0.1:8000')
args.add_argument('--stub-url')
options = args.parse_args()
base = options.base_url.rstrip('/')
artifacts = Path(tempfile.gettempdir()) / 'jmap-operations-review'
artifacts.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base + '/UI/main.html')
    page.wait_for_url('**/operations.html*')
    ready(page)
    page.wait_for_selector('#forecast-chart .forecast-band')
    reference = page.request.get(base + '/reference').json()
    for map_id in ['baseline-map', 'response-map']:
        check(page.locator(f'#{map_id} .simulation-zone').count() == len(reference['zone_order']) == 10, 'Canonical zones render')
        check(page.locator(f'#{map_id} .simulation-edge').count() == len(reference['edge_order']) == 14, 'Canonical corridors render')
    check('not yet trained' in page.locator('#response-heading').inner_text().lower(), 'Agent preview is labelled')
    check(page.locator('#placeholder-banner').is_visible(), 'Optimiser preview is not presented as a trained policy')
    check(page.locator('#forecast-explanation li').count() == 3, 'Forecast has three explanations')
    check('not calibrated' in page.locator('#forecast-explanation').inner_text(), 'Baseline ranges are not passed off as calibrated')
    check('synthetic' in page.locator('#data-status').inner_text().lower(), 'Synthetic data provenance is visible')
    page.screenshot(path=str(artifacts / 'operations-desktop.png'))

    seek(page, 0)
    early_cost = page.locator('#kpi-cost').inner_text()
    seek(page, 47)
    check(page.locator('#kpi-cost').inner_text() != early_cost, 'Cumulative totals follow the selected time')
    page.click('[data-tab="results"]')
    agent_cells = page.locator('#results-body tr[data-strategy="agents"] td').all_inner_texts()
    check('Not yet trained' in agent_cells[0] and agent_cells[1:] == ['—', '—'], 'Placeholder scoreboard withholds copied figures')
    check(page.locator('[data-strategy-detail="agents"] strong').all_inner_texts() == ['—','—'], 'Placeholder carbon and curtailment also remain withheld')
    check('tCO₂' in page.locator('[data-strategy-detail="optimiser"] .result-carbon').inner_text(), 'Each actual strategy shows its carbon result')
    check('%' not in page.locator('#result-headline').inner_text(), 'Near-zero baseline cannot create a percentage headline')
    with page.expect_download() as event:
        page.click('#export-results')
    rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
    agent = next(row for row in rows if row and row[0] == 'agents')
    check(agent[1] == 'Not yet trained' and all(not value for value in agent[2:]), 'Comparison CSV withholds placeholder performance')

    page.select_option('#strategy', 'optimiser')
    ready(page)
    check(not page.locator('#placeholder-banner').is_visible(), 'Actual optimiser has its own view')
    page.click('[data-tab="forecast"]')
    page.select_option('#zone', reference['zone_order'][0])
    page.wait_for_function('(zone)=>document.querySelector("#forecast-chart").getAttribute("aria-label")?.startsWith(zone)', arg=reference['zone_order'][0])
    check(page.locator('#forecast-chart .forecast-median').count() == 1, 'P50 line renders for selected zone')
    page.locator('#response-map .simulation-edge[data-edge-id="SSCO-NORT"]').focus()
    page.keyboard.press('Enter')
    check(page.locator('#edge-title').inner_text() == 'SSCO-NORT', 'Keyboard corridor selection inspects the boundary')
    page.click('#zoom-in')
    centres = page.evaluate('''() => ['baseline-map','response-map'].map(id => {
      const svg = document.getElementById(id), matrix = svg.querySelector('.simulation-zones').transform.baseVal.consolidate().matrix;
      return [(svg.viewBox.baseVal.width/2-matrix.e)/matrix.a,(svg.viewBox.baseVal.height/2-matrix.f)/matrix.d];
    })''')
    check(all(abs(a-b) < 1e-9 for a,b in zip(*centres)), 'Split map geographic camera centres synchronize')
    page.click('#reset-map')
    page.click('#single-view')
    check(not page.locator('.baseline-panel').is_visible(), 'Single response view is available')
    page.click('#split-view')
    seek(page, 20)
    page.click('#play')
    page.wait_for_function('Number(document.querySelector("#time-step").value) > 20', timeout=5000)
    page.click('#play')
    check(page.locator('#play').get_attribute('aria-pressed') == 'false', 'Playback can be paused')

    for scenario in reference['scenarios']:
        page.select_option('#scenario', scenario)
        ready(page)
        check(scenario in page.url, 'Scenario selection persists in URL')
    page.screenshot(path=str(artifacts / 'operations-inspect.png'))

    # Confirm that real incident controls post canonical payloads and regenerate state.
    page.select_option('#scenario', 'b6_trip_windy_peak')
    ready(page)
    before = page.request.get(base + '/compare?scenario=b6_trip_windy_peak').json()['revision']
    page.click('#open-incidents')
    page.fill('#incident-start', '0')
    page.fill('#incident-duration', '1')
    with page.expect_response(lambda response: response.request.method == 'POST' and '/incident?' in response.url) as posted:
        page.click('[data-preset="boundary"]')
    check(posted.value.status == 200, 'Incident POST succeeds')
    page.wait_for_function('!document.querySelector("#incident-dialog").open', timeout=60000)
    ready(page)
    edge = page.request.get(base + '/state?scenario=b6_trip_windy_peak&strategy=optimiser&t=0').json()['edges']['SSCO-NORT']
    check(edge == {'flow_mw': 0.0, 'limit_mw': 0.0, 'loading_frac': 0.0, 'tripped': True}, 'Full trip is absent rather than healthy')
    check(page.locator('#response-map .simulation-edge[data-edge-id="SSCO-NORT"]').get_attribute('data-band') == 'out', 'Map marks the full trip out of service')
    check(page.request.get(base + '/compare?scenario=b6_trip_windy_peak').json()['revision'] == before + 1, 'Incident invalidates comparison data')

    # A failed reload cannot export prior data labelled with new controls.
    page.route(re.compile(r'.*/state/series\?.*'), lambda route: route.fulfill(status=503, content_type='application/json', body='{"detail":"Intentional integration-test outage"}'))
    page.select_option('#scenario', 'cold_snap')
    page.wait_for_selector('#error-banner:visible')
    check(page.locator('#export-episode').is_disabled() and page.locator('#export-results').is_disabled(), 'Reload failure disables stale exports')
    page.unroute(re.compile(r'.*/state/series\?.*'))
    page.click('#retry')
    ready(page)

    page.click('[data-tab="forecast"]')
    for width, height in [(1440,900), (1366,768), (1024,768), (768,900), (390,844), (320,800)]:
        page.set_viewport_size({'width':width, 'height':height})
        page.wait_for_timeout(150)
        check(page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'No horizontal overflow at {width}')
        if width > 850:
            check(page.evaluate('document.documentElement.scrollHeight <= innerHeight'), f'Compact desktop fits at {width}')
        if width <= 600:
            check(page.locator('#response-map').bounding_box()['width'] >= width - 30, 'Mobile comparison maps keep full width')
    page.screenshot(path=str(artifacts / 'operations-mobile.png'), full_page=True)

    # Same controller, HTTP stubs and file preview: forecasts retain recorded issue time.
    if options.stub_url:
        page.goto(options.stub_url.rstrip('/') + '/UI/operations.html')
        ready(page)
        page.wait_for_selector('#forecast-chart .forecast-band')
        check('stubs' in page.locator('#data-status').inner_text(), 'Read-only API mode is explicit')
        note = page.locator('#forecast-note').inner_text().lower()
        check('recorded' in note and 'replay' in note, 'Read-only forecast is labelled fixed')
    page.goto((Path(__file__).resolve().parents[1] / 'UI/operations.html').as_uri())
    ready(page)
    page.wait_for_selector('#forecast-chart .forecast-band')
    check('Generated demo' in page.locator('#data-status').inner_text(), 'File preview is explicitly bundled')
    page.click('#open-incidents')
    check(not page.locator('.incident-settings').is_visible(), 'Offline preview does not pretend to inject custom incidents')
    page.click('[data-preset="cold"]')
    page.wait_for_function('!document.querySelector("#incident-dialog").open')
    check(page.locator('#scenario').input_value() == 'cold_snap', 'Bundled incident control loads the actual generated scenario')
    check(not errors, 'No JavaScript runtime errors: ' + repr(errors))
    browser.close()
    print(json.dumps({'result':'passed', 'screenshots':str(artifacts), 'checks':'API topology, timeline, cumulative totals, forecasts, signed/tripped corridors, sync, placeholder honesty, exports, real injection, failure recovery, responsive layout, HTTP stubs and file preview'}))
