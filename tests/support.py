"""Import benchmark modules without requiring an external PYTHONPATH."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/benchmark"))

import evaluate  # noqa: E402
import runner  # noqa: E402

__all__ = ["evaluate", "runner"]
