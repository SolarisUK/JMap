"""Serve archived data as HTTP responses for offline browser regressions only."""
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

UI = Path(__file__).resolve().parents[1]


def install_replay_fixture(page):
    if getattr(page, '_replay_fixture_installed', False):
        return
    page._replay_fixture_installed = True
    # Fixture mutations installed by individual tests run before this assignment.
    source = (UI/'assets/simulation-stubs.js').read_text(encoding='utf-8') + '\n' + (UI/'operations-api.js').read_text(encoding='utf-8')
    page.route('**/operations-api.js', lambda route: route.fulfill(status=200, content_type='application/javascript', body=source))

    def respond(route):
        url = urlparse(route.request.url)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        data = page.evaluate('''([path,q])=>{
          const b=window.JMAP_SIMULATION_STUBS;
          if(path==='/reference')return b.reference;
          if(path==='/zones')return b.zones;
          if(path==='/edges')return b.edges;
          if(path==='/scenarios')return b.scenarios;
          if(path==='/state/series')return b.series[q.scenario]?.[q.strategy];
          if(path==='/state')return b.states[q.scenario]?.[q.strategy]?.find(f=>Date.parse(f.timestamp_utc)===Date.parse(q.t));
          if(path==='/compare')return b.compare[q.scenario];
          if(path.startsWith('/forecast/')){
            const forecasts=b.scenario_forecasts?b.scenario_forecasts[q.scenario]:b.forecasts;
            return forecasts?.[decodeURIComponent(path.split('/').at(-1))];
          }
          return null;
        }''', [unquote(url.path), query])
        route.fulfill(status=200 if data is not None else 404,
                      headers={'Access-Control-Allow-Origin': '*'},
                      json=data if data is not None else {'detail': 'Requested fixture is unavailable.'})

    page.route('http://127.0.0.1:8000/**', respond)
