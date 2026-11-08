"""Generate complete API replays and the matching offline UI from Dhruv's simulator.

python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest
Writes only the root stubs/ and UI/assets/simulation-stubs.js; source files are read-only.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile

SCRIPT = Path(__file__).resolve()
UI_ROOT = SCRIPT.parents[1]
STUBS = UI_ROOT.parent / 'stubs'
spec = importlib.util.spec_from_file_location('simulation_builder', SCRIPT.with_name('build-simulation-stubs.py'))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def export(backend_root):
    bundle = builder.build_from_backend(backend_root, allow_seeded_start=True)
    default = bundle['scenarios']['scenarios'][0]['name']
    states = bundle['states'][default]['optimiser']
    # Conventional examples remain available for tools reading the original files.
    payloads = {name: bundle[name] for name in ('reference', 'zones', 'edges', 'scenarios')}
    payloads.update({
        'replay': bundle,
        'compare': bundle['compare'],
        'state_calm': states[min(10, len(states)-1)],
        'state_incident': next((frame for frame in states if frame.get('incidents')), states[0]),
        'state_series': bundle['series'][default]['optimiser'],
        'state_series_none': bundle['series'][default]['none'],
        'state_series_optimiser': bundle['series'][default]['optimiser'],
        'forecast_LOND': bundle['scenario_forecasts'][default]['LOND'],
        'incident_response': {'ok': False, 'detail': 'Read-only replay; select a pre-generated scenario.'},
    })
    # Validate and serialize everything before replacing any working data.
    serialized = {name: json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))
                  for name, value in payloads.items()}
    STUBS.mkdir(exist_ok=True)
    for name, content in serialized.items():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=STUBS, suffix='.tmp', delete=False) as file:
                temporary = Path(file.name)
                file.write(content + '\n')
            temporary.replace(STUBS / f'{name}.json')
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    builder.write_bundle(bundle, builder.DEFAULT_OUTPUT)
    for scenario in bundle['scenarios']['scenarios']:
        print(f"Generated {scenario['name']}: {scenario['episode_start_utc']}, 48 frames per strategy")
    print('API stubs and offline UI now share the same validated replays and final totals.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-root', type=Path, required=True)
    args = parser.parse_args()
    export(args.backend_root)
