"""Verify the running replay API without simulator dependencies or data writes.

Start uvicorn api:app --reload --port 8000, then run:
python -B UI/tests/api-replay.test.py
JMAP_API_BASE can point to a different local server.
"""
from datetime import datetime, timedelta
import json
import math
import os
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = os.environ.get('JMAP_API_BASE', 'http://127.0.0.1:8000').rstrip('/')


def get(path, **params):
    with urlopen(BASE + path + ('?' + urlencode(params) if params else ''), timeout=10) as response:
        return json.load(response)


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class ReplayApiTests(unittest.TestCase):
    def test_every_snapshot_matches_its_own_scenario_strategy_and_interval(self):
        self.assertTrue(get('/health')['ok'])
        reference = get('/reference')
        self.assertEqual(reference['backend_mode'], 'stubs')
        fingerprints = set()
        for scenario in get('/scenarios')['scenarios']:
            name = scenario['name']
            comparison = get('/compare', scenario=name)
            series = {key: get('/state/series', scenario=name, strategy=key) for key in ('none','optimiser')}
            self.assertNotEqual(series['none']['frames'], series['optimiser']['frames'])
            fingerprints.add(json.dumps(series['none']['frames'], sort_keys=True))
            for strategy, run in series.items():
                self.assertEqual(len(run['frames']), 48)
                self.assertEqual(run['scenario'], name)
                self.assertEqual(run['strategy'], strategy)
                start = stamp(run['frames'][0]['timestamp_utc'])
                self.assertEqual(start, stamp(scenario['episode_start_utc']))
                self.assertIn(start.minute, (0, 30))
                self.assertEqual(start.second, 0)
                previous = {}
                for index, frame in enumerate(run['frames']):
                    self.assertEqual(stamp(frame['timestamp_utc']), start + timedelta(minutes=30*index))
                    state = get('/state', scenario=name, strategy=strategy, t=frame['timestamp_utc'])
                    self.assertEqual(state['timestamp_utc'], frame['timestamp_utc'])
                    self.assertEqual(state['scenario'], name)
                    self.assertEqual(state['strategy'], strategy)
                    self.assertEqual(state['zones'], frame['zones'])
                    self.assertEqual(state['edges'], frame['edges'])
                    self.assertEqual(stamp(state['decision_time_utc']), stamp(state['timestamp_utc']) + timedelta(minutes=30))
                    for key, value in state['totals'].items():
                        self.assertTrue(math.isfinite(value))
                        self.assertGreaterEqual(value, previous.get(key, 0))
                    previous = state['totals']
                for key,value in state['totals'].items():
                    self.assertAlmostEqual(value,comparison['strategies'][strategy][key],delta=.051)
                self.assertIn('penalty_gbp', state['totals'])
        self.assertEqual(len(fingerprints), len(get('/scenarios')['scenarios']))

    def test_absent_requests_fail_instead_of_relabelling_another_run(self):
        cases = [('/state/series', {'scenario': 'absent'}, 404),
                 ('/state/series', {'strategy': 'absent'}, 404),
                 ('/state', {'scenario': 'absent'}, 404),
                 ('/state', {'strategy': 'absent'}, 404),
                 ('/state', {'t': '2000-01-01T00:00:00Z'}, 404),
                 ('/state', {'t': 'not-a-date'}, 422),
                 ('/state', {'t': '2025-12-16T00:00:00'}, 422),
                 ('/compare', {'scenario': 'absent'}, 404)]
        for endpoint, params, status in cases:
            with self.subTest(endpoint=endpoint, params=params):
                with self.assertRaises(HTTPError) as error:
                    get(endpoint, **params)
                self.assertEqual(error.exception.code, status)
        scenario = get('/scenarios')['scenarios'][0]
        iso_z = scenario['episode_start_utc'].replace('+00:00', 'Z')
        state = get('/state', scenario=scenario['name'], strategy='none', t=iso_z)
        self.assertEqual(stamp(state['timestamp_utc']), stamp(iso_z))

    def test_forecasts_keep_their_actual_scenario_zone_and_issue_time(self):
        for scenario in get('/scenarios')['scenarios']:
            for zone in get('/reference')['zone_order']:
                forecast = get('/forecast/' + zone, scenario=scenario['name'], issue_time=scenario['episode_start_utc'])
                self.assertEqual(forecast['zone_id'], zone)
                self.assertEqual(stamp(forecast['issue_time_utc']), stamp(scenario['episode_start_utc']))
                self.assertEqual(len(forecast['forecast']), 48)
                self.assertEqual(len(forecast['timestamps_utc']), 48)
                for i, (time, row) in enumerate(zip(forecast['timestamps_utc'], forecast['forecast'])):
                    self.assertEqual(stamp(time), stamp(forecast['issue_time_utc']) + timedelta(minutes=30*i))
                    self.assertLessEqual(row[0], row[1])
                    self.assertLessEqual(row[1], row[2])
        with self.assertRaises(HTTPError) as error:
            get('/forecast/LOND', issue_time='2000-01-01T00:00:00Z')
        self.assertEqual(error.exception.code, 409)


if __name__ == '__main__':
    unittest.main(verbosity=2)
