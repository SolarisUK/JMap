"""B6 release check: runtime scoreboard, prominent outcome and every map frame."""
import json
from pathlib import Path
import re
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

UI = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8000'
PAGE = (UI/'operations.html').as_uri()+'?scenario=b6_trip_windy_peak'


def ready(page):
    page.wait_for_function("(!document.querySelector('#export-transfers').disabled&&document.querySelector('#frame-count').textContent.includes('/ 48'))||!document.querySelector('#error-banner').hidden")
    assert page.locator('#error-banner').is_hidden(), page.locator('#error-message').inner_text()


def valid_numbers(page):
    text = page.locator('body').inner_text()
    assert not re.search(r'\b(?:NaN|Infinity)\b', text), text
    assert not re.search(r'[-\u2212]\s*\u00a3?\s*0(?:\.0+)?(?![\d.,])', text), text


def main():
    with urlopen(BASE+'/compare?scenario=b6_trip_windy_peak', timeout=5) as response:
        comparison = json.load(response)
    baseline, optimiser = (comparison['strategies'][key] for key in ('none', 'optimiser'))
    assert round(baseline['unserved_mwh']) == 53418
    assert round(baseline['cost_gbp']/1e6) == 371
    assert 0 <= optimiser['unserved_mwh'] < .05  # Zero at the dashboard's 0.1 MWh precision.
    assert round(optimiser['cost_gbp']/1e6) == 72
    assert 0 <= optimiser['penalty_gbp'] < 10
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(PAGE)
        ready(page)
        assert page.locator('#result-headline').inner_text() == '0 MWh unserved'
        assert page.locator('#outcome-reduction').text_content() == '100% less unserved energy'
        size = page.locator('#result-headline').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')
        others = page.locator('.kpi-strip strong,.network-state-summary dd').evaluate_all('es=>es.map(e=>parseFloat(getComputedStyle(e).fontSize))')
        assert size > max(others)
        baseline_red = 0
        for step in range(48):
            page.locator('#time-step').evaluate("(e,value)=>{e.value=value;e.dispatchEvent(new Event('input',{bubbles:true}));}", step)
            ready(page)
            assert page.locator('#response-map .simulation-edge[data-band="overload"]').count() == 0, step
            assert page.locator('#corridor-list [data-status="overloaded"]').count() == 0, step
            assert page.locator('#corridor-count').inner_text().startswith('0 overloaded'), step
            baseline_red += page.locator('#baseline-map .simulation-edge[data-band="overload"]').count()
            valid_numbers(page)
        assert baseline_red > 0, 'Real baseline overloads must remain visible.'
        with urlopen(BASE+'/state/series?scenario=b6_trip_windy_peak&strategy=none') as response:
            frames = json.load(response)['frames']
        first_trip = next(frame for frame in frames if frame['edges']['SSCO-NORT']['tripped'])
        display_time = page.evaluate("t=>window.JMapOperations.formatTime(t,{includeDate:true})", first_trip['timestamp_utc'])
        assert display_time in page.locator('#scenario-description').text_content()
        assert page.locator('#scenario option:checked').get_attribute('title') == page.locator('#scenario-description').text_content()
        page.locator('[data-tab="results"]').click()
        metrics = page.locator('#result-other-metrics').evaluate('e=>Object.fromEntries([...e.children].map(r=>[r.querySelector("dt").textContent,r.querySelector("dd").textContent]))')
        assert metrics['Penalty reduction'] == '100%'
        print('PASS B6 scoreboard: 53,418 MWh / ~GBP371M vs 0 MWh / ~GBP72M / GBP5 penalties, from /compare.')
        print('PASS all 48 optimiser frames: zero red overloads; real baseline overloads remain visible.')
        for width in (1440, 390, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.locator('#result-headline').is_visible()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')

        phase = {'positive': False}
        zero_page = browser.new_page(viewport={'width': 1440, 'height': 900})
        zero_page.on('pageerror', lambda error: errors.append(str(error)))

        def zero_comparison(route):
            reply = route.fetch()
            data = reply.json()
            for key in ('none', 'optimiser'):
                data['strategies'][key].update(unserved_mwh=0.0, cost_gbp=0.0, penalty_gbp=0.0)
            data['strategies']['optimiser'].update(unserved_mwh=123.4 if phase['positive'] else -0.0,
                                                   cost_gbp=-1e-10, penalty_gbp=-0.0)
            route.fulfill(response=reply, json=data)

        zero_page.route(BASE+'/compare?*', zero_comparison)
        for positive in (False, True):
            phase['positive'] = positive
            zero_page.goto(PAGE+'&tab=results')
            ready(zero_page)
            assert zero_page.locator('#outcome-reduction').text_content() == ''
            assert zero_page.locator('#result-headline').inner_text() == ('123.4 MWh unserved' if positive else '0 MWh unserved')
            valid_numbers(zero_page)
        assert not errors, errors
        print('PASS zero-baseline and signed-zero API responses: no NaN, infinity, negative zero or invented percentages.')
        print('PASS headline prominence and compact 320/390/1440 layouts.')
        browser.close()


if __name__ == '__main__':
    main()
