"""The saved user list and settings, kept in data/instakeep.json.

Every change re-reads the file, applies the change and writes it back, so the
window and a `--run` (a separate process) don't overwrite each other's
results. Writes go to a temp file first and then replace the real one, so a
crash never leaves a half-written file.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from igdl.security import normalize_username, strip_control

DEFAULT_LIMIT = 5


def default_settings(output_dir: Path) -> dict:
    """Settings for a new store. _clean() also uses this as the list of known keys."""
    return {
        "limit": DEFAULT_LIMIT,
        "all_posts": False,  # True: every post, and "limit" is ignored
        "output_dir": str(output_dir),
        "videos": False,
        "caption": False,
        "tags": True,      # caption #hashtags -> image Tags
        "metadata": False,
    }


# Per-user download records, added up over every run. Each one is a number >= 0.
# media_count and last_* are replaced by each run instead of added up (a run
# that didn't learn media_count keeps the old one), and longest_seconds keeps
# the largest.
STAT_FIELDS = {
    "runs": int,              # finished downloads (not counting failures)
    "seconds": float,         # total time, including pauses and posts already on disk
    "pause_seconds": float,   # time spent in rate-limit pauses
    "posts": int,             # posts looked at
    "new_posts": int,         # posts that saved at least one new file
    "images": int,            # image files downloaded
    "image_seconds": float,   # time spent downloading them
    "videos": int,            # video files downloaded
    "video_seconds": float,
    "queries": int,           # Instagram API requests
    "media_count": int,       # the profile's post count at the last run (0 = unknown)
    "last_seconds": float,    # the most recent run
    "last_images": int,
    "last_videos": int,
    "longest_seconds": float,  # the slowest run
}
_REPLACED_STATS = {"media_count", "last_seconds", "last_images", "last_videos"}
_MAX_STATS = {"longest_seconds"}


def empty_stats() -> dict:
    return {key: kind() for key, kind in STAT_FIELDS.items()}


def _clean_stats(raw: object) -> dict:
    """Valid stats from the file: wrong types and negative numbers become 0."""
    saved = raw if isinstance(raw, dict) else {}
    stats = empty_stats()
    for key, kind in STAT_FIELDS.items():
        value = saved.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            stats[key] = kind(value)
    # Records saved before longest_seconds existed still know their last run.
    stats["longest_seconds"] = max(stats["longest_seconds"], stats["last_seconds"])
    return stats


def merge_stats(old: dict, run: dict) -> dict:
    """old + one run's numbers. Fields in _REPLACED_STATS take the run's value,
    fields in _MAX_STATS the larger of the two."""
    merged = dict(old)
    for key, value in run.items():
        if key not in STAT_FIELDS:
            continue
        if key == "media_count" and not value:
            continue  # unknown this run: keep what an earlier run found
        if key in _REPLACED_STATS:
            merged[key] = value
        elif key in _MAX_STATS:
            merged[key] = max(merged.get(key, 0), value)
        else:
            merged[key] = merged.get(key, 0) + value
    return _clean_stats(merged)


def _optional_text(value: object) -> str | None:
    """A string from the file, made safe to show, or None."""
    return strip_control(value) if isinstance(value, str) else None


def _clean(raw: object, output_dir: Path) -> dict:
    """Turn whatever was in the file into a valid store, dropping bad entries.

    The file is edited by hand sometimes, so nothing in it is trusted: unknown
    keys are dropped, wrong types fall back to the default, and usernames that
    aren't valid are skipped.
    """
    data = raw if isinstance(raw, dict) else {}
    settings = default_settings(output_dir)
    saved = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    for key, default in settings.items():
        value = saved.get(key, default)
        if isinstance(default, bool):
            settings[key] = value if isinstance(value, bool) else default
        elif key == "limit":
            settings[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else default
        else:
            settings[key] = value if isinstance(value, str) and value.strip() else default

    users, seen = [], set()
    for entry in data.get("users", []) if isinstance(data.get("users"), list) else []:
        if not isinstance(entry, dict):
            continue
        try:
            name = normalize_username(str(entry.get("username", "")))
        except ValueError:
            continue
        if name in seen:
            continue
        seen.add(name)
        users.append({
            "username": name,
            "last_run": _optional_text(entry.get("last_run")),
            "last_status": _optional_text(entry.get("last_status")),
            "stats": _clean_stats(entry.get("stats")),
        })
    return {"settings": settings, "users": users}


class Store:
    """Thread-safe access to data/instakeep.json."""

    def __init__(self, path: Path, default_output: Path) -> None:
        self.path = Path(path)
        self.default_output = Path(default_output)
        self._lock = threading.Lock()
        self._data = self._read()

    # ------------------------------------------------------------- file access

    def _read(self) -> dict:
        """The file's contents, cleaned. A missing file gives an empty store."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError):
            # Corrupt file: keep a copy so nothing is lost, then start fresh.
            try:
                shutil.copyfile(self.path, self.path.with_suffix(".json.bak"))
            except OSError:
                pass
            raw = {}
        return _clean(raw, self.default_output)

    def _write(self, data: dict) -> None:
        """Write to a temp file, then swap it in, so a crash can't leave half a file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _mutate(self, change) -> object:
        """Apply change(data) to the latest file contents and save. Returns its result.

        Re-reading first picks up what another process (the window or a --run)
        wrote since we last looked, so its changes aren't overwritten.
        """
        with self._lock:
            data = self._read()
            result = change(data)
            self._write(data)
            self._data = data
            return result

    def reload(self) -> None:
        """Pick up changes another process made (e.g. results from a run)."""
        with self._lock:
            self._data = self._read()

    # ------------------------------------------------------------------ reads

    @property
    def settings(self) -> dict:
        with self._lock:
            return deepcopy(self._data["settings"])

    @property
    def users(self) -> list[dict]:
        with self._lock:
            return deepcopy(self._data["users"])

    def usernames(self) -> list[str]:
        return [u["username"] for u in self.users]

    # ----------------------------------------------------------------- writes

    def add_user(self, name: str) -> bool:
        """Add a user. Returns False if already listed. Raises ValueError if invalid."""
        name = normalize_username(name)

        def change(data):
            if any(u["username"] == name for u in data["users"]):
                return False
            data["users"].append({"username": name, "last_run": None, "last_status": None,
                                  "stats": empty_stats()})
            return True
        return self._mutate(change)

    def remove_user(self, name: str) -> bool:
        """Remove a user. Returns False if it wasn't listed (or isn't a valid name)."""
        try:
            name = normalize_username(name)
        except ValueError:
            return False  # the list only ever holds valid names

        def change(data):
            before = len(data["users"])
            data["users"] = [u for u in data["users"] if u["username"] != name]
            return len(data["users"]) != before
        return self._mutate(change)

    def record_result(self, name: str, status: str, when: datetime | None = None,
                      run_stats: dict | None = None) -> None:
        """Save when `name` was last downloaded and how it went (e.g. 'ok, 3 new').

        run_stats (keys from STAT_FIELDS) are added to the user's records in the
        same write, so the status and the numbers always match.
        """
        stamp = (when or datetime.now()).isoformat(timespec="seconds")

        def change(data):
            for u in data["users"]:
                if u["username"] == name:
                    u["last_run"], u["last_status"] = stamp, status
                    if run_stats:
                        u["stats"] = merge_stats(u.get("stats") or empty_stats(), run_stats)
        self._mutate(change)

    def update_settings(self, **values) -> None:
        """Change settings; values are validated the same way as on load."""
        def change(data):
            merged = {**data["settings"], **values}
            data["settings"] = _clean({"settings": merged}, self.default_output)["settings"]
        self._mutate(change)
