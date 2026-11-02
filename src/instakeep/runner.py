"""Download the newest posts of every saved user, one user at a time.

Used by both the window (on a background thread) and `main-program.py --run`
(no window). Downloading itself is igdl's job: this module only loops over the
users, keeps going when one user fails, records results, and makes sure two
downloads never run at once (RunLock).
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from igdl import cli, downloader
from igdl.security import describe_unexpected, strip_control

from . import paths
from .estimate import format_duration
from .store import Store

# Exit codes of `main-program.py --run`, documented in the README.
EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_RATE_LIMIT = cli.EXIT_RATE_LIMIT  # 4, the same code igdl uses
EXIT_BUSY = 5                          # another run is already in progress
KEEP_LOGS = 30                         # newest log files kept in logs/
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}  # counted as "new files"
STALE_LOCK_SECONDS = 24 * 3600         # a lock this old is ignored, whoever holds it

# igdl exit code -> the short status shown in the "Last downloaded" column.
_SHORT_ERRORS = {
    cli.EXIT_NOT_FOUND: "not found",
    cli.EXIT_PRIVATE: "private",
    cli.EXIT_RATE_LIMIT: "rate-limited",
}


@dataclass
class UserResult:
    """How one user's download went."""
    username: str
    ok: bool
    new_files: int = 0
    seconds: float = 0.0     # how long this user's download took
    status: str = ""
    code: int | None = None  # igdl exit code for failures


# ------------------------------------------------------------------- run lock

def pid_alive(pid: int) -> bool:
    """True if a process with this PID is running."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) would terminate the process on Windows; ask the OS instead.
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class RunLock:
    """A lock file so the window and a --run never download at the same time."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.held = False

    def acquire(self) -> bool:
        """Take the lock. False if another live process holds it.

        O_EXCL makes creating the file atomic: of two processes starting at the
        same moment, only one succeeds. A lock left behind by a crashed process
        is removed and the attempt repeated once.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._is_stale():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                return False
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self.held = True
            return True
        return False

    def _is_stale(self) -> bool:
        """True if the holder is gone, the lock is very old, or the file is unreadable."""
        try:
            pid = int(self.path.read_text().strip() or 0)
            age = time.time() - self.path.stat().st_mtime
        except (OSError, ValueError):
            return True
        return age > STALE_LOCK_SECONDS or not pid_alive(pid)

    def release(self) -> None:
        """Remove the lock file, if we hold it. Safe to call more than once."""
        if self.held:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()


# -------------------------------------------------------------------- the run

def _media_files(folder: Path) -> set[str]:
    """Names of the media files in a user's folder (empty if it doesn't exist yet)."""
    try:
        return {p.name for p in folder.iterdir() if p.suffix.lower() in MEDIA_SUFFIXES}
    except OSError:
        return set()


def run_all(
    store: Store,
    log: Callable[[str], None] = print,
    should_stop: Callable[[], bool] = lambda: False,
    on_pause: Callable[[float], None] | None = None,
    on_user_done: Callable[[UserResult], None] | None = None,
    only: list[str] | None = None,
    build_loader=downloader.build_loader,
    download_user=downloader.download_user,
    describe_error=cli.describe_error,
    on_user_start: Callable[[str], None] | None = None,
) -> list[UserResult]:
    """Download the newest `limit` posts (or all posts) of each saved user, or just `only`.

    One user failing doesn't stop the others, except a rate-limit/connection
    error: the remaining users would hit the same block, so the run ends there.
    Each user's download is timed, and its file counts, times, requests and
    pauses are added to the user's records (used for the time estimates).
    on_user_start(name) is called as each user begins (the window's timer).
    build_loader / download_user / describe_error are igdl's; tests pass fakes.
    """
    s = store.settings  # one snapshot, so a settings change mid-run can't mix values
    names = store.usernames()
    if only is not None:
        wanted = set(only)
        names = [n for n in names if n in wanted]
    if not names:
        log("No users in the list.")
        return []

    output = Path(s["output_dir"])
    loader = build_loader(
        output, videos=s["videos"], caption=s["caption"], metadata=s["metadata"],
        quiet=True, on_pause=on_pause, should_stop=should_stop,
    )
    # Send instaloader's non-fatal warnings to our log too. Every `log` used here
    # strips control characters, so the warning text needs no cleaning of its own.
    try:
        loader.context.error = lambda msg, repeat_at_end=True: log(f"warning: {msg}")
    except AttributeError:
        pass

    limit = None if s["all_posts"] else s["limit"]  # None = every post
    what = "all posts" if limit is None else f"newest {limit}"
    results: list[UserResult] = []
    for i, name in enumerate(names, 1):
        if should_stop():
            log("Stopped.")
            break
        log(f"=== [{i}/{len(names)}] @{name} ({what}) ===")
        if on_user_start:
            on_user_start(name)
        folder = output / name
        before = _media_files(folder)
        stats = downloader.DownloadStats()
        started = time.monotonic()
        try:
            download_user(loader, name, limit, log=log, should_stop=should_stop,
                          tags=s["tags"], stats=stats)
        except Exception as e:  # noqa: BLE001 - record every failure and keep going
            known = describe_error(e, name)
            code, message = known if known else (None, describe_unexpected(e))
            result = UserResult(name, ok=False, status=_SHORT_ERRORS.get(code, "error"), code=code)
            log(f"error: {message}")
        else:
            new = len(_media_files(folder) - before)
            stopped = should_stop()
            result = UserResult(name, ok=not stopped, new_files=new,
                                status=f"stopped, {new} new" if stopped else f"ok, {new} new")
        result.seconds = time.monotonic() - started
        if result.ok:
            log(f"@{name}: {result.new_files} new file(s) "
                f"({stats.images} image(s), {stats.videos} video(s)) in {format_duration(result.seconds)}")
        store.record_result(name, result.status, run_stats=_run_stats(stats, result))
        results.append(result)
        if on_user_done:
            on_user_done(result)
        if result.code == EXIT_RATE_LIMIT:
            # The remaining users would hit the same block, so stop here.
            log("Instagram is blocking requests; skipping the remaining users until the next run.")
            break
    return results


def _run_stats(stats: downloader.DownloadStats, result: UserResult) -> dict:
    """One run's numbers in the store's STAT_FIELDS form.

    Time and files from a failed or stopped run still count towards the totals,
    but only finished runs count as runs (estimates average per run).
    """
    return {
        "runs": int(result.ok),
        "seconds": result.seconds,
        "pause_seconds": stats.pause_seconds,
        "posts": stats.posts,
        "new_posts": stats.new_posts,
        "images": stats.images,
        "image_seconds": stats.image_seconds,
        "videos": stats.videos,
        "video_seconds": stats.video_seconds,
        "queries": stats.queries,
        "media_count": stats.media_count or 0,
        "last_seconds": result.seconds,
        "last_images": stats.images,
        "last_videos": stats.videos,
    }


def exit_code(results: list[UserResult]) -> int:
    """The --run exit code for a finished run (rate-limit beats other failures)."""
    if any(r.code == EXIT_RATE_LIMIT for r in results):
        return EXIT_RATE_LIMIT
    if any(not r.ok for r in results):
        return EXIT_SOME_FAILED
    return EXIT_OK


# ------------------------------------------------------------- headless --run

def open_log(logs_dir: Path = paths.LOGS_DIR):
    """Today's log file (appended to), after deleting all but the newest KEEP_LOGS."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    old = sorted(logs_dir.glob("run-*.log"))
    for stale in old[:-KEEP_LOGS]:
        try:
            stale.unlink()
        except OSError:
            pass
    return open(logs_dir / f"run-{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8")


def make_logger(file) -> Callable[[str], None]:
    """Write to the log file, and to the console if there is one (pythonw has none)."""
    def log(text: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {strip_control(str(text))}"
        file.write(line + "\n")
        file.flush()
        if sys.stdout is not None:
            try:
                print(line)
            except (UnicodeEncodeError, OSError):  # the log file still has the line
                pass
    return log


def run_headless(store: Store) -> int:
    """A run without a window (main-program.py --run): results in logs/run-YYYY-MM-DD.log."""
    with open_log() as f:
        log = make_logger(f)
        lock = RunLock(paths.LOCK_FILE)
        if not lock.acquire():
            log("Another download is already running; skipping this run.")
            return EXIT_BUSY
        with lock:
            log(f"Run started for {len(store.usernames())} user(s).")
            try:
                results = run_all(store, log=log, on_pause=lambda secs: log(downloader.format_pause(secs)))
            except Exception as e:  # noqa: BLE001 - always leave the error and its traceback in the log
                log(f"error: run failed: {describe_unexpected(e)}")
                return EXIT_SOME_FAILED
            code = exit_code(results)
            ok = sum(r.ok for r in results)
            log(f"Finished: {ok}/{len(results)} user(s) OK, "
                f"{sum(r.new_files for r in results)} new file(s). Exit code {code}.")
            return code
