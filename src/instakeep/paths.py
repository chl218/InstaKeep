"""Where InstaKeep keeps its files. Everything lives inside the InstaKeep folder.

All paths are absolute and based on this file's location, not the current folder,
so `main-program.py` works no matter where it's started from.
"""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2]   # .../InstaKeep
SCRIPT = APP_DIR / "main-program.py"
VENV = APP_DIR / ".venv"
DATA_DIR = APP_DIR / "data"
STORE_FILE = DATA_DIR / "instakeep.json"
LOCK_FILE = DATA_DIR / "run.lock"
LOGS_DIR = APP_DIR / "logs"
DEFAULT_OUTPUT = APP_DIR / "downloads"
