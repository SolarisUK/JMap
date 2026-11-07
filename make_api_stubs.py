"""Compatibility entry point for the repository's original root-level command."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).resolve().parent / "scripts/make_api_stubs.py"
    runpy.run_path(str(script), run_name="__main__")
