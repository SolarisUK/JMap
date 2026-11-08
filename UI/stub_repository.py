"""Read standard supplied stubs, optionally enriched with a matching full replay.

Missing detail stays unknown. A replay with a different source fingerprint is
never allowed to override newly supplied observations or scoreboard values.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

TOTALS = ('unserved_mwh', 'cost_gbp', 'penalty_gbp', 'carbon_t', 'curtailed_mwh')


def moment(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class StubRepository:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.version = None
        self.data = None

    def load(self):
        paths = sorted(self.folder.glob('*.json'))
        version = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_ctime_ns, p.stat().st_size, p.stat().st_ino) for p in paths)
        if version != self.version:
            raw = {p.name: p.read_bytes() for p in paths}
            files = {name: json.loads(content.decode('utf-8-sig')) for name, content in raw.items()}
            enriched = files.get('replay.json', {})
            hashes = enriched.get('stub_source_hashes', {})
            matching = bool(hashes) and all(name in raw and hashlib.sha256(raw[name]).hexdigest() == expected for name, expected in hashes.items())
            self.data = enriched if matching else self._standard(files)
            self.version = version
        return self.data

    @staticmethod
    def _standard(files):
        data = {key: deepcopy(files[key+'.json']) for key in ('reference', 'zones', 'edges')}
        data.update(series={}, states={}, scenario_forecasts={})
        data['reference']['backend_mode'] = 'stubs'
        for filename, payload in files.items():
            if not filename.startswith('state_series') or not isinstance(payload, dict) or not payload.get('frames'):
                continue
            scenario, strategy = payload.get('scenario'), payload.get('strategy')
            if not scenario or strategy not in ('none', 'optimiser'):
                continue
            data['series'].setdefault(scenario, {})[strategy] = deepcopy(payload)
        supported = {name for name, runs in data['series'].items() if {'none', 'optimiser'} <= runs.keys()}
        listed = files.get('scenarios.json', {}).get('scenarios', [])
        data['scenarios'] = {'scenarios': []}
        for name in sorted(supported):
            metadata = next((deepcopy(row) for row in listed if row['name'] == name), {'name': name, 'description': name})
            start = data['series'][name]['none']['frames'][0]['timestamp_utc']
            metadata.update(episode_start_utc=start, start_timestamp_utc=start)
            data['scenarios']['scenarios'].append(metadata)
            data['states'][name] = {}
            for strategy in ('none', 'optimiser'):
                data['states'][name][strategy] = []
                for index, frame in enumerate(data['series'][name][strategy]['frames']):
                    snapshot = deepcopy(frame)
                    snapshot.update(scenario=name, strategy=strategy, step_index=index)
                    snapshot.setdefault('totals', {key: None for key in TOTALS})
                    # The conventional examples are optimiser snapshots. Only
                    # use one when its timestamp and measurements agree.
                    if strategy == 'optimiser':
                        for key in ('state_calm.json', 'state_incident.json'):
                            example = files.get(key)
                            if example and StubRepository._matches(example, frame):
                                snapshot = deepcopy(example)
                                snapshot.update(scenario=name, strategy=strategy, step_index=index)
                                break
                    data['states'][name][strategy].append(snapshot)
            forecasts = {}
            for filename, payload in files.items():
                if filename.startswith('forecast_') and payload.get('zone_id') and payload.get('issue_time_utc'):
                    if moment(payload['issue_time_utc']) == moment(start):
                        forecasts[payload['zone_id']] = deepcopy(payload)
            data['scenario_forecasts'][name] = forecasts
        return data

    @staticmethod
    def _matches(example, frame):
        if moment(example['timestamp_utc']) != moment(frame['timestamp_utc']):
            return False
        for group in ('zones', 'edges'):
            for key, fields in frame[group].items():
                supplied = example.get(group, {}).get(key, {})
                for field, value in fields.items():
                    other = supplied.get(field)
                    if isinstance(value, bool):
                        if other is not value:
                            return False
                    elif isinstance(value, (int, float)) and isinstance(other, (int, float)):
                        tolerance = .00051 if field in ('storage_soc', 'loading_frac') else .051
                        if abs(value-other) > tolerance:
                            return False
                    elif value != other:
                        return False
        return True
