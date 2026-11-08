"""Immutable, fingerprint-keyed float64 forecasts for independent histories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np

import schemas as S


def cache_directory(model_dir, fingerprint):
    if (not isinstance(fingerprint, str) or not fingerprint
            or fingerprint in (".", "..") or Path(fingerprint).name != fingerprint):
        raise ValueError("Cache fingerprint must be one non-empty path component")
    return Path(model_dir) / "forecast_cache" / fingerprint


def _issues(issue_times):
    if (not isinstance(issue_times, list) or not issue_times
            or any(not isinstance(value, str) or not value for value in issue_times)
            or len(set(issue_times)) != len(issue_times) or issue_times != sorted(issue_times)):
        raise ValueError("Cache issue times must be a non-empty, unique, sorted list of strings")
    return list(issue_times)


def _shape(issue_times):
    return (len(issue_times), S.N_ZONES, S.FORECAST_HORIZON, len(S.QUANTILES))


def _validate_values(values, issue_times):
    if not isinstance(values, np.ndarray) or values.dtype != np.dtype("float64"):
        raise ValueError("Forecast cache values must retain float64 predictions")
    if values.shape != _shape(issue_times):
        raise ValueError("Forecast cache shape differs from its issue/zone/horizon contract")
    if not np.isfinite(values).all() or (np.diff(values, axis=-1) < 0).any():
        raise ValueError("Forecast cache values must be finite with ordered quantiles")


def _sha256(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def load_cache(model_dir, fingerprint, issue_times):
    """Return a read-only mmap, or a miss; an existing invalid cache is an error."""
    issue_times = _issues(issue_times)
    directory = cache_directory(model_dir, fingerprint)
    if not directory.exists():
        return None, {}
    try:
        metadata = json.loads((directory / "metadata.json").read_text())
        if not isinstance(metadata, dict):
            raise ValueError("Cache metadata must be an object")
        if metadata.get("fingerprint") != fingerprint:
            raise ValueError("Cache fingerprint differs from the requested model/data fingerprint")
        if metadata.get("issue_times") != issue_times:
            raise ValueError("Cache issue times differ from the loaded history")
        if metadata.get("shape") != list(_shape(issue_times)) or metadata.get("dtype") != "float64":
            raise ValueError("Cache metadata has a different shape or dtype")
        values_path = directory / "values.npy"
        if metadata.get("cache_sha256") != _sha256(values_path):
            raise ValueError("Cache values checksum differs from metadata")
        values = np.load(values_path, mmap_mode="r", allow_pickle=False)
        _validate_values(values, issue_times)
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f"Invalid forecast cache at {directory}: {error}") from error
    return values, {value: index for index, value in enumerate(issue_times)}


def write_cache(model_dir, fingerprint, issue_times, values, *, metadata=None):
    """Publish a complete cache atomically; never replace an existing fingerprint."""
    issue_times = _issues(issue_times)
    directory = cache_directory(model_dir, fingerprint)
    if directory.exists():
        raise FileExistsError(f"Forecast cache already exists: {directory}")
    _validate_values(values, issue_times)
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("Extra cache metadata must be an object")
    detail = dict(metadata or {})
    reserved = {"fingerprint", "cache_sha256", "issue_times", "shape", "dtype"}
    if reserved.intersection(detail):
        raise ValueError("Extra metadata cannot replace forecast cache identity or shape fields")
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{fingerprint}.", dir=directory.parent))
    try:
        values_path = staging / "values.npy"
        np.save(values_path, values, allow_pickle=False)
        detail.update({"fingerprint": fingerprint, "cache_sha256": _sha256(values_path),
                       "issue_times": issue_times, "shape": list(values.shape), "dtype": "float64"})
        (staging / "metadata.json").write_text(json.dumps(detail, indent=2, allow_nan=False) + "\n")
        if directory.exists():
            raise FileExistsError(f"Forecast cache was published concurrently: {directory}")
        staging.rename(directory)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return detail
