"""Run the supplied team checker with the project's schema, on any OS.

The original checker is unmodified. This launcher supplies its schema import
and turns its `problems` list into a meaningful process exit status.
"""

from __future__ import annotations

import argparse
import importlib.util
import runpy
import sys
from pathlib import Path


def run_checker(root: Path, parquet: Path) -> int:
    # -I ignores PYTHONIOENCODING. Set the pipe encoding in this process so
    # Windows writes UTF-8 even when its default redirected encoding is cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    checker = root / "scripts/check_parquet.py"
    schema = root / "schemas.py"
    if not checker.is_file() or not schema.is_file():
        raise FileNotFoundError(f"Expected {checker} and {schema}")
    # Preload the actual project module before the old checker inserts its
    # obsolete /home/claude path. No contract values or checks are replaced.
    sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("schemas", schema)
    module = importlib.util.module_from_spec(spec)
    sys.modules["schemas"] = module
    spec.loader.exec_module(module)
    sys.argv = [str(checker), str(parquet)]
    result = runpy.run_path(str(checker), run_name="__main__")
    problems = result.get("problems")
    if not isinstance(problems, list):
        raise RuntimeError("This checker did not expose the expected problems list")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parquet", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    raise SystemExit(run_checker(args.root.resolve(), args.parquet.resolve()))


if __name__ == "__main__":
    main()
