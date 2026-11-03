"""Download the newest posts of every saved user, one user at a time.

Used by both the window (on a background thread) and `instakeep.py --run`
(no window). Downloading itself is igdl's job: this module only loops over the
users, keeps going when one user fails, records results, follows renamed
accounts, and makes sure two downloads never run at once (RunLock).
"""

from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from igdl import cli, downloader
from igdl.security import describe_unexpected, strip_control

from . import awake, paths
from .bootstrap import EXIT_SETUP
from .estimate import format_duration
from .store import NewerStoreError, Store, folder_name

# Exit codes of `instakeep.py --run`, documented in the README.
EXIT_OK = 0
EXIT_SOME_FAILED = 1
EXIT_RATE_LIMIT = cli.EXIT_RATE_LIMIT  # 4, the same code igdl uses
EXIT_BUSY = 5                          # another run is already in progress
KEEP_LOGS = 30                         # newest log files kept in logs/
MEDIA_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".mp4"}  # counted as "new files"
HEARTBEAT_SECONDS = 60                 # how often the holder touches the lock file
STALE_LOCK_SECONDS = 3600              # a lock not touched for this long is ignored

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
    """A lock file so the window and a --run never download at the same time.

    While held, a background thread touches the file every `heartbeat` seconds.
    A lock whose holder has died, or that hasn't been touched for
    STALE_LOCK_SECONDS, is taken over. So a run of any length keeps its lock,
    and a crashed one (even if its PID was reused) frees it within the hour.
    """

    def __init__(self, path: Path, heartbeat: float = HEARTBEAT_SECONDS) -> None:
        self.path = Path(path)
        self.heartbeat = heartbeat
        self.held = False
        self._stop_beat = threading.Event()
        self._beat: threading.Thread | None = None

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
            self._start_heartbeat()
            return True
        return False

    def _start_heartbeat(self) -> None:
        self._stop_beat.clear()
        self._beat = threading.Thread(target=self._keep_fresh, daemon=True)
        self._beat.start()

    def _keep_fresh(self) -> None:
        """Runs on the heartbeat thread: update the lock file's time until released."""
        while not self._stop_beat.wait(self.heartbeat):
            try:
                os.utime(self.path)
            except OSError:
                return  # the file is gone; nothing left to keep fresh

    def _is_stale(self) -> bool:
        """True if the holder is gone, the lock wasn't touched lately, or the file is unreadable."""
        try:
            pid = int(self.path.read_text().strip() or 0)
            age = time.time() - self.path.stat().st_mtime
        except (OSError, ValueError):
            return True
        return age > STALE_LOCK_SECONDS or not pid_alive(pid)

    def release(self) -> None:
        """Remove the lock file, if we hold it. Safe to call more than once."""
        if self.held:
            self._stop_beat.set()
            if self._beat is not None:
                self._beat.join(timeout=5)
                self._beat = None
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


def run_order(users: list[dict], only: list[str] | None) -> list[str]:
    """The usernames to download, in the order to download them.

    A full run (only=None) starts with whoever went longest without a successful
    download (never first), so when a rate limit ends runs early, the users at
    the end of the list still get their turn. Ties keep the list order.
    A run of selected users keeps the list order.
    """
    if only is not None:
        wanted = set(only)
        return [u["username"] for u in users if u["username"] in wanted]
    # ISO timestamps sort by time; "" (never) sorts first. sorted() is stable.
    return [u["username"] for u in sorted(users, key=lambda u: u.get("last_ok") or "")]


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
    lookup_username=downloader.username_for_id,
) -> list[UserResult]:
    """Download the newest `limit` posts (or all posts) of each saved user, or just `only`.

    One user failing doesn't stop the others, except a rate-limit/connection
    error: the remaining users would hit the same block, so the run ends there.
    Each user's download is timed, and its file counts, times, requests and
    pauses are added to the user's records (used for the time estimates).
    on_user_start(name) is called as each user begins (the window's timer).
    An "all posts" run of a user who was fully downloaded before stops at posts
    already on disk. A user who isn't found is looked up by their saved ID, and
    a renamed account is switched to its new name (see _follow_rename).

    Raises NewerStoreError before downloading anything if a newer InstaKeep
    wrote the data file (it couldn't record the results).
    build_loader / download_user / describe_error / lookup_username are igdl's;
    tests pass fakes.
    """
    store.check_writable()  # also picks up the other process's latest changes
    s = store.settings  # one snapshot, so a settings change mid-run can't mix values
    users = {u["username"]: u for u in store.users}
    names = run_order(list(users.values()), only)
    if not names:
        log("No users in the list.")
        return []
    if not (s["images"] or s["videos"]):
        log("Nothing to download: Images and Videos are both off. Turn one of them on.")
        return []

    output = Path(s["output_dir"])
    loader = build_loader(
        output, videos=s["videos"], images=s["images"], caption=s["caption"], metadata=s["metadata"],
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
        user = users[name]
        folder = output / folder_name(user)
        before = _media_files(folder)
        stats = downloader.DownloadStats()
        started = time.monotonic()
        try:
            download_user(loader, name, limit, log=log, should_stop=should_stop,
                          tags=s["tags"], stats=stats, folder_name=folder_name(user),
                          stop_at_known=limit is None and user["full_scan_done"])
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
        store.record_result(name, result.status, run_stats=_run_stats(stats, result),
                            ok=result.ok, userid=stats.userid,
                            full_scan=result.ok and stats.complete)
        blocked = False
        if result.code == cli.EXIT_NOT_FOUND and user["userid"]:
            blocked = _follow_rename(store, loader, user, log, lookup_username, describe_error)
        results.append(result)
        if on_user_done:
            on_user_done(result)
        if result.code == EXIT_RATE_LIMIT or blocked:
            # The remaining users would hit the same block, so stop here.
            log("Instagram is blocking requests; skipping the remaining users until the next run.")
            break
    return results


def _follow_rename(store: Store, loader, user: dict, log: Callable[[str], None],
                   lookup_username, describe_error) -> bool:
    """@name wasn't found: look its saved ID up, and switch the list to the new name.

    The folder stays the old one, so the history stays in one place. The new name
    is downloaded from the next run. Returns True if the lookup was rate-limited
    (the run should end, like any rate limit).
    """
    name = user["username"]
    try:
        new = lookup_username(loader, user["userid"])
    except Exception as e:  # noqa: BLE001 - the user already failed; a failed check must not end the others
        known = describe_error(e, name)
        log(f"Couldn't check whether @{name} was renamed: {known[1] if known else describe_unexpected(e)}")
        return bool(known) and known[0] == EXIT_RATE_LIMIT
    if new is None or new == name:
        log(f"@{name}: no account with its ID either. It may have been deleted, "
            "or Instagram wouldn't say without a login.")
        return False
    if store.rename_user(name, new):
        log(f"@{name} is now called @{new}. The list now uses @{new}; its posts keep going "
            f"into the '{folder_name(user)}' folder. It's downloaded from the next run.")
    else:
        log(f"@{name} is now called @{new}, which is already in the list. "
            f"Remove @{name} if it's no longer needed.")
    return False


def _run_stats(stats: downloader.DownloadStats, result: UserResult) -> dict:
    """One run's numbers in the store's STAT_FIELDS form.

    Time and files from a failed or stopped run still count towards the totals,
    but only finished runs count as runs (estimates average per run).

    Without a login Instagram doesn't always give the profile's post count. A
    finished run that looked at every post (stats.complete) knows it, so that
    number is used instead (with videos off it counts image posts only, which
    is what such a run downloads). A run that stopped early at posts already on
    disk doesn't: it saw only the newest few.
    """
    media_count = stats.media_count or 0
    if not media_count and stats.complete and result.ok:
        media_count = stats.posts
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
        "media_count": media_count,
        "last_seconds": result.seconds,
        "last_images": stats.images,
        "last_videos": stats.videos,
        "longest_seconds": result.seconds,
    }


def exit_code(results: list[UserResult]) -> int:
    """The --run exit code for a finished run (rate-limit beats other failures)."""
    if any(r.code == EXIT_RATE_LIMIT for r in results):
        return EXIT_RATE_LIMIT
    if any(not r.ok for r in results):
        return EXIT_SOME_FAILED
    return EXIT_OK


# ------------------------------------------------------------- headless --run

def open_log(logs_dir: Path | None = None):
    """Today's log file (appended to), after deleting all but the newest KEEP_LOGS.

    logs_dir defaults to paths.LOGS_DIR, looked up when called (tests redirect it).
    """
    logs_dir = logs_dir or paths.LOGS_DIR
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
    """A run without a window (instakeep.py --run): results in logs/run-YYYY-MM-DD.log."""
    with open_log() as f:
        log = make_logger(f)
        lock = RunLock(paths.LOCK_FILE)
        if not lock.acquire():
            log("Another download is already running; skipping this run.")
            return EXIT_BUSY
        with lock:
            log(f"Run started for {len(store.usernames())} user(s).")
            try:
                with awake.keep_awake(log=log):  # no sleep mid-run, even when locked
                    results = run_all(store, log=log,
                                      on_pause=lambda secs: log(downloader.format_pause(secs)))
            except NewerStoreError as e:
                log(f"error: {e}")
                return EXIT_SETUP
            except Exception as e:  # noqa: BLE001 - always leave the error and its traceback in the log
                log(f"error: run failed: {describe_unexpected(e)}")
                return EXIT_SOME_FAILED
            code = exit_code(results)
            ok = sum(r.ok for r in results)
            log(f"Finished: {ok}/{len(results)} user(s) OK, "
                f"{sum(r.new_files for r in results)} new file(s). Exit code {code}.")
            return code
