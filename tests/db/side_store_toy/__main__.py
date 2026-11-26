"""Run one stand-in server: ``python -m tests.db.side_store_toy <uri> <gate> <id> <body>``."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.db.side_store_toy import first_use_in_new_process

first_use_in_new_process(sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4])
