"""Compatibility entry point; implementation lives in scripts/make_api_stubs.py."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "scripts" / "make_api_stubs.py"), run_name="__main__")
