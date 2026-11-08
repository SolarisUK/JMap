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
    with urlopen(BASE+'/state/series?scenario=b6_trip_windy_peak&strategy=none') as response:
        frames = json.load(response)['frames']
    assert round(baseline['unserved_mwh']) == 63917
    assert round(baseline['cost_gbp']/1e6,1) == 388.5
    assert 0 <= optimiser['unserved_mwh'] < .05  # Zero at the dashboard's 0.1 MWh precision.
    assert round(optimiser['cost_gbp']/1e6,1) == 17.4
    assert 0 <= optimiser['penalty_gbp'] < 10
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(PAGE)
        cdp = page.context.new_cdp_session(page)
        cdp.send('Network.enable')
        cdp.send('Network.setCacheDisabled', {'cacheDisabled': True})
        cdp.send('Page.reload', {'ignoreCache': True})
        ready(page)
        assert page.locator('#baseline-heading').inner_text() == 'No response (network-blind dispatch)'
        assert page.locator('#data-status').text_content() == 'Real-data replay'
        assert 'synthetic' not in page.locator('body').text_content().lower()
        assert 'demo data' not in page.locator('body').text_content().lower()
        assert 'agents' not in page.locator('body').text_content().lower()
        assert '14 Dec 2025' in page.locator('#frame-time').inner_text()
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
            if frames[step]['incidents']:
                for zone in ('NORT','YORK','WALE','MIDL','EAST','SWES','LOND','SOUT'):
                    assert frames[step]['zones'][zone]['unserved_mw'] > .05
                    assert page.locator(f'#baseline-map .simulation-zone-label[data-zone-id="{zone}"] .simulation-zone-node').get_attribute('fill') != '#d4eae1'
                for zone in ('NSCO','SSCO'):
                    assert frames[step]['zones'][zone]['unserved_mw'] < .05
                    assert page.locator(f'#baseline-map .simulation-zone-label[data-zone-id="{zone}"] .simulation-zone-node').get_attribute('fill') == '#d4eae1'
            valid_numbers(page)
        assert baseline_red > 0, 'Real baseline overloads must remain visible.'
        first_trip = next(frame for frame in frames if any(incident['type']=='line_trip' for incident in frame['incidents']))
        display_time = page.evaluate("t=>window.JMapOperations.formatTime(t,{includeDate:true})", first_trip['timestamp_utc'])
        assert display_time in page.locator('#scenario-description').text_content()
        assert '17:00' in display_time
        assert page.locator('#scenario option:checked').get_attribute('title') == page.locator('#scenario-description').text_content()
        page.locator('[data-tab="results"]').click()
        metrics = page.locator('#result-other-metrics').evaluate('e=>Object.fromEntries([...e.children].map(r=>[r.querySelector("dt").textContent,r.querySelector("dd").textContent]))')
        assert metrics['Penalty reduction'] == '100%'
        assert page.locator('[data-metric="penalty_gbp"] [data-strategy="optimiser"] span').inner_text() == '\u00a30.0M'
        assert page.locator('[data-metric="cost_gbp"] [data-strategy="none"] span').inner_text() == '\u00a3388.5M'
        assert page.locator('[data-metric="cost_gbp"] [data-strategy="optimiser"] span').inner_text() == '\u00a317.4M'
        assert 'Scotland is islanded with surplus wind and stays supplied' in page.locator('#scenario-description').text_content()
        assert 'all eight England and Wales zones' in page.locator('#scenario-description').text_content()
        assert page.locator('#results-table th').all_text_contents() == ['No response (network-blind dispatch)','Optimiser']
        print('PASS real-data B6 scoreboard: 63,917 MWh / GBP388.5M vs 0 MWh / GBP17.4M, from /compare.')
        print('B6 raw optimiser penalty (preserved):',optimiser['penalty_gbp'])
        print('PASS all 48 optimiser frames: zero red overloads; real baseline overloads remain visible.')
        print('PASS after 17:00: Scotland stays supplied; all eight England and Wales zones develop shortfalls.')
        for width in (1440, 390, 320):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.locator('#result-headline').is_visible()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')

        page.set_viewport_size({'width':1440,'height':900})
        for scenario,date,baseline_mwh,response_mwh,response_cost,baseline_cost in (
            ('cold_snap','10 Jan 2025',10592,3053,96.0,None),
            ('nuclear_outage_low_wind','09 Nov 2024',0,0,49.5,50.0),
        ):
            with urlopen(BASE+'/compare?scenario='+scenario) as response:
                totals = json.load(response)['strategies']
            assert round(totals['none']['unserved_mwh']) == baseline_mwh
            assert round(totals['optimiser']['unserved_mwh']) == response_mwh
            assert round(totals['optimiser']['cost_gbp']/1e6,1) == response_cost
            if baseline_cost is not None:
                assert round(totals['none']['cost_gbp']/1e6,1) == baseline_cost
            page.locator('#scenario').select_option(scenario)
            ready(page)
            assert date in page.locator('#frame-time').inner_text()
            expected = page.evaluate("n=>n.toLocaleString('en-GB',{maximumFractionDigits:1,signDisplay:'negative'})",totals['optimiser']['unserved_mwh'])
            assert page.locator('#result-headline').inner_text() == expected+' MWh unserved'
            valid_numbers(page)
        print('PASS cold-snap and nuclear release totals and all three real episode dates.')

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
            data['strategies']['agents'] = dict(data['strategies']['optimiser'])
            data['agents_is_placeholder'] = True
            route.fulfill(response=reply, json=data)

        zero_page.route(BASE+'/compare?*', zero_comparison)
        for positive in (False, True):
            phase['positive'] = positive
            zero_page.goto(PAGE+'&tab=results')
            ready(zero_page)
            assert zero_page.locator('#outcome-reduction').text_content() == ''
            assert zero_page.locator('#result-headline').inner_text() == ('123.4 MWh unserved' if positive else '0 MWh unserved')
            assert zero_page.locator('#results-table th').all_text_contents() == ['No response (network-blind dispatch)','Optimiser']
            assert 'agents' not in zero_page.locator('body').text_content().lower()
            valid_numbers(zero_page)
        assert not errors, errors
        print('PASS zero-baseline and signed-zero API responses: no NaN, infinity, negative zero or invented percentages.')
        print('PASS headline prominence and compact 320/390/1440 layouts.')
        browser.close()


if __name__ == '__main__':
    main()
