"""Check the API-only dashboard against its runtime responses.

python -B UI/tests/api-replay-browser.py
Requires uvicorn on port 8000, Python Playwright and Chromium.
"""
import csv
import io
import json
from pathlib import Path
import tempfile
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8000'


def get(path, **params):
    with urlopen(BASE+path+('?' + urlencode(params) if params else ''), timeout=10) as response:
        return json.load(response)


def money(value):
    return '\u00a3' + f'{value/1e6:,.2f}'.rstrip('0').rstrip('.') + 'm' if abs(value) >= 1e6 else f'\u00a3{value:,.0f}'


def ready(page):
    page.wait_for_function("(!document.querySelector('#export-transfers').disabled && document.querySelector('#frame-count').textContent.includes('/ 48')) || !document.querySelector('#error-banner').hidden")
    assert page.locator('#error-banner').is_hidden(), page.locator('#error-message').inner_text()


def check_api_only(browser):
    """Change API responses while withholding all bundled numerical data."""
    reference = get('/reference')
    scenarios = get('/scenarios')['scenarios']
    edge_id, zone_id = reference['edge_order'][0], reference['zone_order'][0]
    phase = {'version': 1, 'failed': False}
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    requests, errors = [], []
    page.on('request', lambda request: requests.append(request.url))
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.route('**/assets/simulation-stubs.js', lambda route: route.fulfill(
        status=200, content_type='application/javascript', body='/* No bundled data in API audit. */'))

    def state_response(route):
        if phase['failed']:
            route.fulfill(status=503, content_type='application/json',
                          headers={'Access-Control-Allow-Origin': '*'},
                          body=json.dumps({'detail': 'API audit temporarily unavailable'}))
            return
        response = route.fetch()
        data = response.json()
        baseline = parse_qs(urlparse(route.request.url).query)['strategy'][0] == 'none'
        for zone in data['zones'].values():
            zone['unserved_mw'] = 0
        data['zones'][zone_id]['unserved_mw'] = 41.25 if baseline else 0
        data['edges'][edge_id].update(flow_mw=-987.25 if baseline else 321.5,
                                      limit_mw=1000, loading_frac=.98725 if baseline else .3215, tripped=False)
        data['totals'].update(cost_gbp=9870000 if baseline else 12340000,
                              penalty_gbp=4560000 if baseline else 7890000)
        route.fulfill(response=response, json=data)

    def compare_response(route):
        response = route.fetch()
        data = response.json()
        data['strategies']['none'].update(unserved_mwh=8000, cost_gbp=90000000, penalty_gbp=4000000)
        data['strategies']['optimiser'].update(unserved_mwh=2000 if phase['version'] == 1 else 1600,
                                               cost_gbp=40000000 if phase['version'] == 1 else 41000000,
                                               penalty_gbp=7000000)
        route.fulfill(response=response, json=data)

    def forecast_response(route):
        response = route.fetch()
        data = response.json()
        centres = [5000+11*h if phase['version'] == 1 else 7000+7*h+(h % 5)*200 for h in range(48)]
        data['forecast'] = [[mid*.8, mid, mid*1.2] for mid in centres]
        data['explanation'] = [f"API audit payload v{phase['version']}.", 'Quantiles returned by the API.', 'No bundled forecast data is loaded.']
        route.fulfill(response=response, json=data)

    page.route(BASE+'/state?*', state_response)
    page.route(BASE+'/compare?*', compare_response)
    page.route(BASE+'/forecast/**', forecast_response)
    page.goto((UI/'operations.html').as_uri()+'?'+urlencode({'mode': 'api', 'api': BASE}))
    ready(page)
    assert page.evaluate('window.JMAP_SIMULATION_STUBS === undefined')
    assert page.locator('#maps').evaluate('e=>!e.classList.contains("single")')
    assert page.locator('#baseline-map').is_visible() and page.locator('#response-map').is_visible()
    baseline = page.locator(f'#baseline-map .simulation-edge[data-edge-id="{edge_id}"]')
    response = page.locator(f'#response-map .simulation-edge[data-edge-id="{edge_id}"]')
    assert 'Signed flow: -987.25 MW' in baseline.get_attribute('aria-label')
    assert 'Signed flow: 321.5 MW' in response.get_attribute('aria-label')
    assert baseline.get_attribute('data-reverse') == 'true'
    assert response.get_attribute('data-reverse') == 'false'
    assert baseline.get_attribute('data-band') == 'warning'
    assert response.get_attribute('data-band') == 'healthy'
    assert '41.3 MW' in page.locator('#baseline-summary').inner_text()
    assert page.locator('#kpi-cost').inner_text() == money(12340000)
    assert page.locator('#kpi-penalty').inner_text() == money(7890000)

    page.locator('[data-tab="forecast"]').click()
    page.wait_for_function("document.querySelector('#forecast-explanation').textContent.includes('API audit payload v1.')")
    assert 'P50 5000 MW' in page.locator('#forecast-chart circle title').first.text_content()
    first_curve = page.locator('#forecast-chart .forecast-median').get_attribute('d')
    page.locator('[data-tab="results"]').click()
    assert '75%' in page.locator('#result-headline').inner_text()
    assert page.locator('[data-metric="cost_gbp"] [data-strategy="optimiser"] span').inner_text() == money(40000000)
    assert page.locator('[data-metric="penalty_gbp"] [data-strategy="optimiser"] span').inner_text() == money(7000000)
    assert page.locator('#results-table th').all_text_contents() == ['No response','Optimiser']
    assert page.locator('#results-body tr').count() == 5

    phase['version'] = 2
    page.locator('#scenario').select_option(scenarios[1]['name'])
    ready(page)
    assert '80%' in page.locator('#result-headline').inner_text()
    assert page.locator('[data-metric="cost_gbp"] [data-strategy="optimiser"] span').inner_text() == money(41000000)
    page.locator('[data-tab="forecast"]').click()
    page.wait_for_function("document.querySelector('#forecast-explanation').textContent.includes('API audit payload v2.')")
    assert 'P50 7000 MW' in page.locator('#forecast-chart circle title').first.text_content()
    assert page.locator('#forecast-chart .forecast-median').get_attribute('d') != first_curve
    assert any(urlparse(url).path == '/zones' for url in requests)
    assert any(urlparse(url).path == '/edges' for url in requests)
    assert any(urlparse(url).path == '/forecast/LOND' for url in requests)
    assert any(urlparse(url).path == '/compare' for url in requests)

    phase['failed'] = True
    page.locator('[data-tab="transfers"]').click()
    page.locator('#next-frame').click()
    page.wait_for_selector('#error-banner:not([hidden])')
    assert 'API audit temporarily unavailable' in page.locator('#error-message').inner_text()
    assert page.locator('#export-transfers').is_disabled()
    assert page.locator('#use-bundle').count() == 0
    assert page.evaluate('window.JMAP_SIMULATION_STUBS === undefined')
    assert not errors, errors
    context.close()
    print('PASS API-only: changed network data, signed directions, forecasts, scoreboards and penalties render without a bundle; API failures remain visible')


def run():
    scenarios = get('/scenarios')['scenarios']
    with tempfile.TemporaryDirectory(dir=UI/'tests', prefix='replay-browser-') as directory, sync_playwright() as p:
        browser = p.chromium.launch(downloads_path=directory)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url))
        for mode in ('api',):
            url = (UI/'operations.html').as_uri()
            page.goto(url)
            ready(page)
            for scenario in scenarios:
                name = scenario['name']
                page.locator('#scenario').select_option(name)
                ready(page)
                series = get('/state/series', scenario=name, strategy='optimiser')
                for step in (0, 38, 47):
                    page.locator('#time-step').evaluate("(e,step)=>{e.value=step;e.dispatchEvent(new Event('input',{bubbles:true}));}", step)
                    ready(page)
                    timestamp = series['frames'][step]['timestamp_utc']
                    expected = get('/state', scenario=name, strategy='optimiser', t=timestamp)
                    baseline = get('/state', scenario=name, strategy='none', t=timestamp)
                    display_time = page.evaluate("t=>new Intl.DateTimeFormat('en-GB',{timeZone:'Europe/London',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(t))", timestamp)
                    assert display_time in page.locator('#frame-time').inner_text()
                    assert page.locator('#frame-count').inner_text() == f'{step+1} / 48'
                    assert page.locator('#kpi-cost').inner_text() == money(expected['totals']['cost_gbp']), (mode, name, step, page.locator('#kpi-cost').inner_text(), money(expected['totals']['cost_gbp']))
                    assert page.locator('#kpi-penalty').inner_text() == money(expected['totals']['penalty_gbp'])
                    for map_id, snapshot in (('#response-map', expected), ('#baseline-map', baseline)):
                        for edge_id, edge in snapshot['edges'].items():
                            aria = page.locator(f'{map_id} .simulation-edge[data-edge-id="{edge_id}"]').get_attribute('aria-label')
                            expected_flow = page.evaluate('n=>String(n)', edge['flow_mw'])
                            assert f'Signed flow: {expected_flow} MW' in aria, (mode, name, step, edge_id)
                    if step == 38:
                        assert expected['edges'] != baseline['edges'] or expected['zones'] != baseline['zones'], (mode, name, 'identical runs')
                page.locator('[data-tab="results"]').click()
                comparison = get('/compare', scenario=name)
                for key in ('none', 'optimiser'):
                    totals = comparison['strategies'][key]
                    assert page.locator(f'[data-metric="cost_gbp"] [data-strategy="{key}"] span').inner_text() == money(totals['cost_gbp'])
                    assert page.locator(f'[data-metric="penalty_gbp"] [data-strategy="{key}"] span').inner_text() == money(totals['penalty_gbp'])
                assert page.locator('#response-heading').inner_text() == 'Optimiser'
                assert page.locator('#baseline-heading').inner_text() == 'No response'
                assert page.locator('#result-honesty').inner_text() == 'RL agents were also trained; they did not beat the optimiser.'
                with page.expect_download() as event:
                    page.locator('#export-results').click()
                rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
                header = next(i for i, row in enumerate(rows) if row and row[0] == 'Strategy')
                values = {row[0]: dict(zip(rows[header], row)) for row in rows[header+1:]}
                for key in ('none', 'optimiser'):
                    assert float(values[key]['Cost GBP']) == comparison['strategies'][key]['cost_gbp']
                    assert float(values[key]['Penalty GBP (model)']) == comparison['strategies'][key]['penalty_gbp']
                assert set(values) == {'none','optimiser'}
                assert page.locator('#results-table th').all_text_contents() == ['No response','Optimiser']
                page.locator('[data-tab="forecast"]').click()
                page.wait_for_function("document.querySelector('#forecast-status').textContent.includes('Illustrative')")
                assert page.locator('#forecast-chart path').count() > 0
                page.locator('[data-tab="transfers"]').click()
            print(f'PASS {mode}: all scenarios and selected times, distinct split-map measurements, separate penalties, /compare scoreboard and CSV, recorded forecasts')
        assert page.evaluate('window.JMAP_SIMULATION_STUBS === undefined')
        strategy_requests = [parse_qs(urlparse(url).query)['strategy'][0] for url in requests if urlparse(url).path in ('/state','/state/series')]
        assert set(strategy_requests) == {'none','optimiser'}
        state_requests = [parse_qs(urlparse(url).query) for url in requests if urlparse(url).path == '/state']
        assert {'none', 'optimiser'} == {query['strategy'][0] for query in state_requests}
        assert {row['name'] for row in scenarios} <= {parse_qs(urlparse(url).query)['scenario'][0] for url in requests if urlparse(url).path == '/compare'}
        for width in (1440, 390, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            page.wait_for_timeout(100)
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'), width
            boxes = page.locator('.kpi-strip article').evaluate_all('items=>items.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}})')
            assert len(boxes) == 5
            for selector in ('#kpi-cost', '#kpi-penalty'):
                assert page.locator(selector).is_visible()
            for index, box in enumerate(boxes):
                assert box['left'] >= 0 and box['right'] <= width, (width, box)
                for other in boxes[index+1:]:
                    assert not (box['left'] < other['right']-.5 and box['right'] > other['left']+.5 and box['top'] < other['bottom']-.5 and box['bottom'] > other['top']+.5)
        assert not errors, errors
        print('PASS compact 320/390/1440 layouts and no browser errors')
        context.close()
        check_api_only(browser)
        browser.close()


if __name__ == '__main__':
    run()
