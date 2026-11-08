"""Check both dashboard modes against the running replay API and its /compare.

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


def run():
    scenarios = get('/scenarios')['scenarios']
    with tempfile.TemporaryDirectory(dir=UI/'tests', prefix='replay-browser-') as directory, sync_playwright() as p:
        browser = p.chromium.launch(downloads_path=directory)
        context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
        page = context.new_page()
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url))
        for mode in ('api', 'bundled'):
            url = (UI/'operations.html').as_uri() + '?' + urlencode({'mode': mode, 'api': BASE})
            page.goto(url)
            ready(page)
            for scenario in scenarios:
                name = scenario['name']
                page.locator('#scenario').select_option(name)
                ready(page)
                series = get('/state/series', scenario=name, strategy='agents')
                for step in (0, 38, 47):
                    page.locator('#time-step').evaluate("(e,step)=>{e.value=step;e.dispatchEvent(new Event('input',{bubbles:true}));}", step)
                    ready(page)
                    timestamp = series['frames'][step]['timestamp_utc']
                    expected = get('/state', scenario=name, strategy='agents', t=timestamp)
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
                    assert page.locator(f'#results-body tr[data-strategy="{key}"] td').nth(2).inner_text() == money(totals['cost_gbp'])
                    assert page.locator(f'[data-strategy-detail="{key}"] .result-penalty').inner_text() == money(totals['penalty_gbp'])
                assert page.locator('#response-heading').inner_text() == 'Optimiser preview'
                with page.expect_download() as event:
                    page.locator('#export-results').click()
                rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding='utf-8-sig'))))
                header = next(i for i, row in enumerate(rows) if row and row[0] == 'Strategy')
                values = {row[0]: dict(zip(rows[header], row)) for row in rows[header+1:]}
                for key in ('none', 'optimiser'):
                    assert float(values[key]['Cost GBP']) == comparison['strategies'][key]['cost_gbp']
                    assert float(values[key]['Penalty GBP (model)']) == comparison['strategies'][key]['penalty_gbp']
                assert values['agents']['Status'] == 'Not yet trained'
                assert values['agents']['Penalty GBP (model)'] == ''
                page.locator('[data-tab="forecast"]').click()
                page.wait_for_function("document.querySelector('#forecast-status').textContent.includes('Illustrative')")
                assert page.locator('#forecast-chart path').count() > 0
                page.locator('[data-tab="transfers"]').click()
            print(f'PASS {mode}: all scenarios and selected times, distinct split-map measurements, separate penalties, /compare scoreboard and CSV, recorded forecasts')
        state_requests = [parse_qs(urlparse(url).query) for url in requests if urlparse(url).path == '/state']
        assert {'none', 'agents'} <= {query['strategy'][0] for query in state_requests}
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
        browser.close()


if __name__ == '__main__':
    run()
