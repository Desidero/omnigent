"""Make the goal loop's package importable from its source tree."""

import sys
from pathlib import Path

_SOURCE = Path(__file__).parents[3] / "ext-demo" / "extensions" / "goal-loop" / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))
