"""Residual RL wrapper: PPO learns a correction to the optimiser, not the whole action.

With a zero correction the wrapped env behaves exactly like OptimiserAgent, so training starts
from the best known strategy instead of from "every plant at 50%". The policy can only improve on
the optimiser by learning when and how to depart from it.

    import grid_env, residual_env
    env = residual_env.ResidualEnv(grid_env.GridEnv())
    # train PPO on env exactly as before

At evaluation, wrap the same way: the policy's output is a correction, not an action.
"""

from __future__ import annotations

import gymnasium as gym
import numpy as np

import agents_baseline as AB
import schemas as S

DEFAULT_SCALE = 0.3  # max correction per action element, in [-1, 1] action units


class ResidualEnv(gym.Wrapper):
    def __init__(self, env: gym.Env, scale: float = DEFAULT_SCALE, base=None):
        super().__init__(env)
        self.base = base if base is not None else AB.OptimiserAgent()
        self.scale = float(scale)
        self._obs = None
        self._info = None

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self._obs, self._info = obs, info
        if hasattr(self.base, "reset"):
            self.base.reset()
        return obs, info

    def base_action(self) -> np.ndarray:
        return self.base.act(self._obs, self._info)

    def step(self, correction):
        corr = np.asarray(correction, dtype=np.float64).reshape(S.N_ZONES, S.ACT_DIM)
        action = np.clip(self.base_action() + self.scale * corr, S.ACTION_LOW, S.ACTION_HIGH)
        obs, reward, terminated, truncated, info = self.env.step(action.astype(np.float32))
        self._obs, self._info = obs, info
        return obs, reward, terminated, truncated, info


class ResidualPolicyAgent(AB.Agent):
    """Wraps a trained residual policy so it has the same .act() interface as the baselines."""

    name = "agents"

    def __init__(self, model, vec_normalize=None, scale: float = DEFAULT_SCALE, base=None):
        self.model = model
        self.vec_normalize = vec_normalize
        self.scale = float(scale)
        self.base = base if base is not None else AB.OptimiserAgent()

    def act(self, obs, info):
        o = np.asarray(obs, dtype=np.float32)
        if self.vec_normalize is not None:
            o = self.vec_normalize.normalize_obs(o)
        corr, _ = self.model.predict(o, deterministic=True)
        corr = np.asarray(corr, dtype=np.float64).reshape(S.N_ZONES, S.ACT_DIM)
        base = self.base.act(obs, info)
        return np.clip(base + self.scale * corr, S.ACTION_LOW, S.ACTION_HIGH).astype(np.float32)
