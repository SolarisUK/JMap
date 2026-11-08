"""Exercise fixed per-scenario dates and refreshed scores using offline fixtures.

Run: python -B UI/tests/simulation-refresh-browser.py
"""
import csv
import io
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
UI = Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory(dir=UI/"tests", prefix="replay-browser-") as directory:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(downloads_path=directory)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""(() => {
              let bundle;
              Object.defineProperty(window,'JMAP_SIMULATION_STUBS',{configurable:true,get:()=>bundle,set:value=>{
                bundle=value;
                const original=structuredClone(value), templates=original.scenarios.scenarios;
                bundle.scenarios={scenarios:[]};bundle.series={};bundle.states={};bundle.compare={};bundle.scenario_forecasts={};
                for(let index=0;index<6;index++){
                  const source=templates[index%templates.length],name=`fixed_day_${index}`;
                  const start=`2026-11-${10+index}T00:00:00.000Z`,delta=Date.parse(start)-Date.parse(source.start_timestamp_utc);
                  const shift=stamp=>new Date(Date.parse(stamp)+delta).toISOString();
                  bundle.scenarios.scenarios.push({...source,name,episode_start_utc:start,start_timestamp_utc:start});
                  bundle.series[name]={};bundle.states[name]={};
                  const strategies={};
                  for(const strategy of original.reference.strategies){
                    const series=structuredClone(original.series[source.name][strategy]);
                    series.scenario=name;
                    series.frames.forEach(frame=>frame.timestamp_utc=shift(frame.timestamp_utc));
                    const states=structuredClone(original.states[source.name][strategy]);
                    states.forEach((frame,step)=>{
                      frame.scenario=name;frame.timestamp_utc=shift(frame.timestamp_utc);
                      const final=(index+1)*(strategy==='none'?1000:200);
                      frame.totals={unserved_mwh:final*(step+1)/48,cost_gbp:final*10*(step+1)/48,carbon_t:final/2*(step+1)/48,curtailed_mwh:0};
                    });
                    bundle.series[name][strategy]=series;bundle.states[name][strategy]=states;
                    strategies[strategy]=structuredClone(states.at(-1).totals);
                  }
                  bundle.compare[name]={scenario:name,strategies,agents_is_placeholder:true};
                  bundle.scenario_forecasts[name]=structuredClone(original.scenario_forecasts?.[source.name]||original.forecasts);
                  for(const forecast of Object.values(bundle.scenario_forecasts[name])){
                    forecast.issue_time_utc=start;forecast.timestamps_utc=forecast.timestamps_utc.map(shift);
                  }
                }
                // Deliberately retain the old global date/forecasts: the UI must use the scenario.
              }});
            })();""")
            page.goto((UI/"operations.html").as_uri())
            page.wait_for_function("!document.querySelector('#export-episode').disabled")
            assert page.locator("#scenario option").count() == 6
            for index in range(6):
                name = f"fixed_day_{index}"
                page.locator("#scenario").select_option(name)
                page.wait_for_function("!document.querySelector('#export-episode').disabled")
                assert page.locator("#error-banner").is_hidden()
                assert f"{10+index:02d} Nov" in page.locator("#episode-range").inner_text()
                page.locator('[data-tab="forecast"]').click()
                page.wait_for_function("document.querySelector('#forecast-status').textContent.includes('Illustrative')")
                assert f"{10+index:02d} Nov" in page.locator("#forecast-issued").inner_text()
                assert page.locator("#forecast-chart path").count() > 0
                page.locator('[data-tab="results"]').click()
                assert "80%" in page.locator("#result-headline").inner_text()
                assert "80.0%" in page.locator("#result-description").inner_text()
                with page.expect_download() as event:
                    page.locator("#export-results").click()
                rows = list(csv.reader(io.StringIO(Path(event.value.path()).read_text(encoding="utf-8-sig"))))
                header = next(i for i, row in enumerate(rows) if row and row[0] == "Strategy")
                metrics = {row[0]: dict(zip(rows[header], row)) for row in rows[header+1:]}
                assert float(metrics['none']['Unserved MWh']) == (index+1)*1000
                assert float(metrics['optimiser']['Unserved MWh']) == (index+1)*200
                assert metrics['agents']['Status'] == 'Not yet trained'
                assert metrics['agents']['Unserved MWh'] == ''
            print('PASS six fixed-date scenarios show their own timelines, forecasts and refreshed scores; placeholders stay withheld')
            page.locator('[data-tab="forecast"]').click()
            page.wait_for_function("document.querySelector('#forecast-chart path')")
            page.evaluate("delete JMAP_SIMULATION_STUBS.scenario_forecasts.fixed_day_5")
            page.locator('[data-tab="forecast"]').click()
            page.wait_for_function("document.querySelector('#forecast-status').textContent==='Forecast unavailable'")
            assert page.locator("#forecast-issued").inner_text() == ''
            assert page.locator("#forecast-chart path").count() == 0
            assert not errors, errors
            print('PASS absent scenario forecast clears the chart instead of substituting a different day')
            browser.close()


if __name__ == '__main__':
    run()
