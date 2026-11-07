"""Offline replay refresh checks; no simulator dependencies or backend writes.

Run: python -B UI/tests/simulation-bundle.test.py
"""
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

UI = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("simulation_builder", UI/"scripts"/"build-simulation-stubs.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReplayRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.current = builder.read_bundle(builder.DEFAULT_OUTPUT)

    def test_current_preview_has_matching_scoreboards_and_timelines(self):
        builder.validate_bundle(self.current)

    def test_refuses_changed_scoreboard_or_shifted_strategy_timeline(self):
        name = self.current["scenarios"]["scenarios"][0]["name"]
        changed = deepcopy(self.current)
        changed["compare"][name]["strategies"]["optimiser"]["cost_gbp"] += 100
        with self.assertRaisesRegex(ValueError, "scoreboard"):
            builder.validate_bundle(changed)
        shifted = deepcopy(self.current)
        shifted["series"][name]["none"]["frames"][1]["timestamp_utc"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "half-hours"):
            builder.validate_bundle(shifted)

    def test_rejects_forecast_from_another_scenario_day(self):
        changed = deepcopy(self.current)
        name = changed["scenarios"]["scenarios"][0]["name"]
        zone = changed["reference"]["zone_order"][0]
        changed["scenario_forecasts"] = {name: deepcopy(changed["forecasts"])}
        changed["scenario_forecasts"][name][zone]["issue_time_utc"] = "2020-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "different scenario start"):
            builder.validate_bundle(changed)

    def test_invalid_refresh_preserves_existing_output_and_output_stays_in_ui(self):
        with tempfile.TemporaryDirectory(dir=UI/"tests", prefix="replay-refresh-") as directory:
            output = Path(directory)/"bundle.js"
            output.write_text("previous data", encoding="utf-8")
            with self.assertRaises((ValueError, KeyError)):
                builder.write_bundle({}, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous data")
        with self.assertRaisesRegex(ValueError, "inside UI"):
            builder.write_bundle(self.current, UI.parent/"forbidden.js")

    def test_missing_scenarios_fail_without_changing_the_bundled_preview(self):
        before = builder.digest(builder.DEFAULT_OUTPUT)
        with tempfile.TemporaryDirectory(dir=UI/"tests", prefix="missing-scenarios-") as directory:
            with self.assertRaisesRegex(ValueError, "Sync the scenario JSON"):
                builder.build_from_backend(directory)
        self.assertEqual(builder.digest(builder.DEFAULT_OUTPUT), before)

    def test_six_scenarios_use_the_helper_for_every_strategy_and_keep_each_start(self):
        calls = []
        class Demand:
            def __getitem__(self, key):
                return 1000
        class Environment:
            def __init__(self, name, scenario):
                self.name, self.scenario, self.demand, self.t0 = name, scenario, Demand(), 0
            def reset(self, seed):
                self.index = 0
                calls.append((self.name, seed, self.scenario["selected_from"]))
                return None, {"timestamp_utc": self.scenario["episode_start_utc"]}
            def step(self, action):
                self.index += 1
                totals = {key: self.index*(action+1) for key in builder.TOTAL_FIELDS}
                info = {"timestamp_utc": (builder.utc(self.scenario["episode_start_utc"])+timedelta(minutes=30*self.index)).isoformat(), "zones": {"A": {"demand_mw": 1000}}, "edges": {}, "incidents": [], "totals": totals}
                return None, 0, self.index == 48, False, info
            def close(self):
                pass
        with tempfile.TemporaryDirectory(dir=UI/"tests", prefix="six-scenarios-") as directory:
            root = Path(directory).resolve()
            folder = root/"scenarios"
            folder.mkdir()
            for name in ("grid_env.py", "schemas.py", "_fake.parquet"):
                (root/name).write_text("test fixture", encoding="utf-8")
            agents = root/"agents_baseline.py"
            agents.write_text("class NoOpAgent:\n def reset(self): pass\n def act(self, observation, info): return 1\nclass OptimiserAgent(NoOpAgent):\n def act(self, observation, info): return 0\n", encoding="utf-8")
            scenarios = {}
            for index in range(6):
                name = f"scenario_{index}"
                scenarios[name] = {"description": name, "episode_start_utc": f"2026-11-{index+1:02d}T00:00:00Z", "selected_from": "_fake.parquet", "incidents": []}
                (folder/f"{name}.json").write_text(json.dumps(scenarios[name]), encoding="utf-8")
            def make_scenario_env(name, **kwargs):
                self.assertEqual(kwargs, {"random_incidents": False})
                return Environment(name, scenarios[name])
            grid = SimpleNamespace(make_scenario_env=make_scenario_env, DEFAULT_DATA="_fake.parquet")
            zone = SimpleNamespace(id="A", name="Test zone", demand_share=1, storage_mwh=0, dr_mw=0, lon=0, lat=51)
            schema = SimpleNamespace(SCENARIO_DIR="scenarios", SCENARIOS=tuple(scenarios)[:3], STEPS_PER_EPISODE=48, CONTRACT_VERSION="test", ZONE_ORDER=("A",), EDGE_ORDER=(), FUEL_ORDER=("GAS",), ZONES=[zone], EDGES=[])
            schema.STRATEGIES = ("none", "optimiser", "agents")
            schema.FUELS, schema.INCIDENT_TYPES = [], []
            schema.QUANTILE_NAMES = ("p10", "p50", "p90")
            schema.QF = SimpleNamespace(OK=0)
            schema.OBS_DIM, schema.ACT_DIM = 52, 11
            schema.FORECAST_HORIZON, schema.DISPLAY_TZ = 48, "Europe/London"
            with patch.dict(sys.modules, {"grid_env": grid, "schemas": schema}):
                bundle = builder.build_from_backend(root)
            self.assertEqual(len(bundle["scenarios"]["scenarios"]), 6)
            self.assertEqual(len(calls), 12)
            for name in scenarios:
                self.assertEqual(sum(call[0] == name for call in calls), 2)
                self.assertEqual(bundle["scenario_forecasts"][name]["A"]["issue_time_utc"], scenarios[name]["episode_start_utc"])
                self.assertEqual(bundle["compare"][name]["strategies"]["none"]["unserved_mwh"], 96)
                self.assertEqual(bundle["compare"][name]["strategies"]["optimiser"]["unserved_mwh"], 48)
                self.assertTrue(bundle["compare"][name]["agents_is_placeholder"])
            output = root/"refreshed.js"
            builder.write_bundle(bundle, output)
            self.assertEqual(builder.read_bundle(output), bundle)


if __name__ == "__main__":
    unittest.main(verbosity=2)
