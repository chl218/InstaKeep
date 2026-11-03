"""The saved user list and settings, kept in data/instakeep.json.

Every change re-reads the file, applies the change and writes it back, so the
window and a `--run` (a separate process) don't overwrite each other's
results. Writes go to a temp file first and then replace the real one, so a
crash never leaves a half-written file.

The file carries a data version (STORE_VERSION). An older file is upgraded on
load (MIGRATIONS). A newer one, written by a newer InstaKeep, can still be read
but is never saved over: this version would drop the fields it doesn't know.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Callable

from igdl.security import normalize_username, strip_control

DEFAULT_LIMIT = 5

# The data version this code reads and writes. Files from before versions
# existed count as 1. Bump it whenever the file's layout changes, and add a
# step to MIGRATIONS if old data needs more than _clean()'s defaults.
STORE_VERSION = 2

# version -> a function that upgrades raw file data from that version to the
# next, in place. 1 -> 2 only added per-user fields (userid, folder,
# full_scan_done, last_ok), which _clean() fills in with defaults.
MIGRATIONS: dict[int, Callable[[dict], None]] = {}


class NewerStoreError(Exception):
    """The data file was written by a newer InstaKeep, so this one won't save to it."""

    def __init__(self, path: Path, version: int) -> None:
        super().__init__(
            f"{path.name} was saved by a newer version of InstaKeep (data version {version}; "
            f"this one understands up to {STORE_VERSION}), so nothing was saved. "
            "Restart InstaKeep to use the new version.")
        self.version = version


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


def _file_version(data: dict) -> int:
    """The data version a file says it has. No (or a nonsense) version means 1."""
    version = data.get("version")
    if isinstance(version, int) and not isinstance(version, bool) and version >= 1:
        return version
    return 1


def _migrate(data: dict, version: int) -> None:
    """Upgrade raw file data from `version` to STORE_VERSION, in place."""
    for step in range(version, STORE_VERSION):
        if step in MIGRATIONS:
            MIGRATIONS[step](data)


def _optional_name(value: object) -> str | None:
    """A valid (lowercase) username from the file, or None."""
    if not isinstance(value, str):
        return None
    try:
        return normalize_username(value)
    except ValueError:
        return None


def _optional_id(value: object) -> int | None:
    """An Instagram user ID from the file (a positive whole number), or None."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def new_user(name: str) -> dict:
    """A user entry as stored in the file."""
    return {"username": name, "last_run": None, "last_status": None, "last_ok": None,
            "userid": None, "folder": None, "full_scan_done": False, "stats": empty_stats()}


def folder_name(user: dict) -> str:
    """The user's folder under the output folder. Usually the username; after a
    rename it stays the old name, so the history stays in one place."""
    return user.get("folder") or user["username"]


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
        user = new_user(name)
        user.update(
            last_run=_optional_text(entry.get("last_run")),
            last_status=_optional_text(entry.get("last_status")),
            last_ok=_optional_text(entry.get("last_ok")),
            userid=_optional_id(entry.get("userid")),
            # The folder becomes part of a path, so it must pass the username check too.
            folder=_optional_name(entry.get("folder")),
            full_scan_done=entry.get("full_scan_done") is True,
            stats=_clean_stats(entry.get("stats")),
        )
        users.append(user)
    return {"version": STORE_VERSION, "settings": settings, "users": users}


class Store:
    """Thread-safe access to data/instakeep.json."""

    def __init__(self, path: Path, default_output: Path) -> None:
        self.path = Path(path)
        self.default_output = Path(default_output)
        self._lock = threading.Lock()
        self.too_new = False  # True: the file is from a newer InstaKeep (see NewerStoreError)
        self._data = self._read()

    # ------------------------------------------------------------- file access

    def _read(self) -> dict:
        """The file's contents, upgraded and cleaned. A missing file gives an empty store.

        Sets self.too_new when the file's version is newer than STORE_VERSION.
        Its data is still returned, so the window can show it.
        """
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
        if not isinstance(raw, dict):
            raw = {}
        version = _file_version(raw)
        self.too_new = version > STORE_VERSION
        self.file_version = version
        _migrate(raw, version)
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
        Raises NewerStoreError, without writing, if a newer InstaKeep wrote the file.
        """
        with self._lock:
            data = self._read()
            if self.too_new:
                self._data = data  # still show what's there
                raise NewerStoreError(self.path, self.file_version)
            result = change(data)
            self._write(data)
            self._data = data
            return result

    def reload(self) -> None:
        """Pick up changes another process made (e.g. results from a run)."""
        with self._lock:
            self._data = self._read()

    def check_writable(self) -> None:
        """Re-read the file and raise NewerStoreError if this version may not save to it.

        Called before a download starts, so a run doesn't download everything and
        then fail to record it.
        """
        self.reload()
        if self.too_new:
            raise NewerStoreError(self.path, self.file_version)

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

    def folder_of(self, name: str) -> str:
        """The folder name for `name`: its saved folder if listed, else the name itself."""
        for user in self.users:
            if user["username"] == name:
                return folder_name(user)
        return name

    # ----------------------------------------------------------------- writes

    def add_user(self, name: str) -> bool:
        """Add a user. Returns False if already listed. Raises ValueError if invalid."""
        name = normalize_username(name)

        def change(data):
            if any(u["username"] == name for u in data["users"]):
                return False
            data["users"].append(new_user(name))
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
                      run_stats: dict | None = None, ok: bool = False,
                      userid: int | None = None, full_scan: bool = False) -> None:
        """Save when `name` was last downloaded and how it went (e.g. 'ok, 3 new').

        run_stats (keys from STAT_FIELDS) are added to the user's records in the
        same write, so the status and the numbers always match. ok=True also sets
        last_ok (the run order uses it). userid, if known, is saved so a renamed
        account can be found again. full_scan=True: this run went through every
        post, so later "all posts" runs may stop early at posts already on disk.
        """
        stamp = (when or datetime.now()).isoformat(timespec="seconds")

        def change(data):
            for u in data["users"]:
                if u["username"] == name:
                    u["last_run"], u["last_status"] = stamp, status
                    if ok:
                        u["last_ok"] = stamp
                    if _optional_id(userid):
                        u["userid"] = userid
                    if full_scan:
                        u["full_scan_done"] = True
                    if run_stats:
                        u["stats"] = merge_stats(u.get("stats") or empty_stats(), run_stats)
        self._mutate(change)

    def rename_user(self, old: str, new: str) -> bool:
        """The account @old is now called @new: switch the list entry to the new name.

        Its folder stays the old one, so new posts land next to the earlier ones.
        Returns False (and changes nothing) if @old isn't listed or @new already is.
        Raises ValueError if `new` isn't a valid username.
        """
        new = normalize_username(new)

        def change(data):
            if any(u["username"] == new for u in data["users"]):
                return False
            for u in data["users"]:
                if u["username"] == old:
                    u["folder"] = folder_name(u)
                    u["username"] = new
                    return True
            return False
        return self._mutate(change)

    def request_full_scan(self, names: list[str]) -> int:
        """Make the next "all posts" run of these users look at every post again
        (to fill gaps), instead of stopping at posts already on disk. Returns how
        many listed users were changed."""
        wanted = set()
        for name in names:
            try:
                wanted.add(normalize_username(name))
            except ValueError:
                continue  # the list only ever holds valid names

        def change(data):
            hits = [u for u in data["users"] if u["username"] in wanted]
            for u in hits:
                u["full_scan_done"] = False
            return len(hits)
        return self._mutate(change)

    def update_settings(self, **values) -> None:
        """Change settings; values are validated the same way as on load."""
        def change(data):
            merged = {**data["settings"], **values}
            data["settings"] = _clean({"settings": merged}, self.default_output)["settings"]
        self._mutate(change)
