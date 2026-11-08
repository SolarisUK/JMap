"""Verify standard-folder replacement against an isolated compatible API.

Uses the API runtime through PYTHONPATH; never edits the real stubs/ or api.py.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
BASE = 'http://127.0.0.1:8001'


def get(path, **query):
    with urlopen(BASE+path+('?' + urlencode(query) if query else ''), timeout=5) as response:
        return json.load(response)


def main():
    with tempfile.TemporaryDirectory(dir=ROOT/'UI/tests', prefix='folder-swap-') as temporary:
        workspace = Path(temporary).resolve()
        target = workspace/'stubs'
        shutil.copytree(ROOT/'dhruv_latest/stubs', target)
        assert not (target/'replay.json').exists()
        environment = dict(os.environ, JMAP_STUBS_DIR=str(target), PYTHONDONTWRITEBYTECODE='1')
        process = subprocess.Popen([sys.executable, '-B', '-m', 'uvicorn', 'UI.api_loader:app', '--port', '8001'],
                                   cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    if get('/health')['ok']:
                        break
                except OSError:
                    time.sleep(.05)
            else:
                raise AssertionError('Isolated API did not start.')
            comparison = get('/compare')
            assert comparison['strategies']['optimiser']['unserved_mwh'] == 0
            series = get('/state/series', strategy='optimiser')
            scenario, timestamp = series['scenario'], series['frames'][0]['timestamp_utc']
            for strategy in ('none', 'optimiser'):
                frames = get('/state/series', scenario=scenario, strategy=strategy)['frames']
                assert len(frames) == 48
                for frame in frames:
                    snapshot = get('/state', scenario=scenario, strategy=strategy, t=frame['timestamp_utc'])
                    assert snapshot['timestamp_utc'] == frame['timestamp_utc']
            reduced = get('/state', scenario=scenario, strategy='none', t=timestamp)
            assert all(value is None for value in reduced['totals'].values())
            print('PASS standard 12-file folder works without replay.json; all 96 B6 snapshots keep their actual timestamps.')

            replacement = workspace/'replacement'
            shutil.copytree(ROOT/'dhruv_latest/stubs', replacement)
            score = json.loads((replacement/'compare.json').read_text())
            score[scenario]['strategies']['optimiser']['unserved_mwh'] = 432.1
            (replacement/'compare.json').write_text(json.dumps(score), encoding='utf-8')
            run = json.loads((replacement/'state_series_optimiser.json').read_text())
            zone = next(iter(run['frames'][0]['zones']))
            run['frames'][0]['zones'][zone]['unserved_mw'] = 432.1
            (replacement/'state_series_optimiser.json').write_text(json.dumps(run), encoding='utf-8')
            # An old optional replay must not override freshly swapped source files.
            shutil.copy2(ROOT/'stubs/replay.json', replacement/'replay.json')
            assert target.resolve().is_relative_to(workspace) and target.name == 'stubs'
            shutil.rmtree(target)
            shutil.copytree(replacement, target)
            assert get('/health')['ok']
            assert get('/compare')['strategies']['optimiser']['unserved_mwh'] == 432.1
            assert get('/state', scenario=scenario, strategy='optimiser', t=timestamp)['zones'][zone]['unserved_mw'] == 432.1
            assert process.poll() is None
            print('PASS replacing only the folder updates API values without restart and rejects a stale optional replay.')
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
