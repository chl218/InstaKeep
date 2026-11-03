"""Keep the computer from going to sleep while a download runs.

Without this, a locked computer can go to sleep (or, on PCs with "Modern
Standby", into standby once the screen turns off), and the download pauses
until someone wakes it. The screen itself may still turn off and lock; only
sleep is held off, and only for as long as the download runs.

  Windows: SetThreadExecutionState(ES_SYSTEM_REQUIRED). The request belongs to
           the calling thread, so start and stop from the downloading thread.
           Windows also drops it if that thread ends.
  macOS:   `caffeinate -i -w <pid>` (ends by itself if this program exits).
  Linux:   `systemd-inhibit --what=sleep:idle ... sleep infinity`, if available.

Standard library only. If the system offers no way to do it, downloads still
run; keep_awake() just says so through `log`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from typing import Callable, Iterator

# Windows SetThreadExecutionState flags.
ES_CONTINUOUS = 0x80000000       # the setting lasts until changed (not a one-off nudge)
ES_SYSTEM_REQUIRED = 0x00000001  # don't sleep, even when idle or the screen is off


def _windows_set(flags: int) -> bool:
    import ctypes
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))


def awake_command(platform: str, pid: int, which: Callable[[str], str | None] = shutil.which) -> list[str] | None:
    """The command that holds off sleep on macOS/Linux while it runs, or None."""
    if platform == "darwin" and which("caffeinate"):
        # -i: no idle sleep. -w: stop when this process exits, even if it crashes.
        return ["caffeinate", "-i", "-w", str(pid)]
    if platform.startswith("linux") and which("systemd-inhibit"):
        return ["systemd-inhibit", "--what=sleep:idle", "--who=InstaKeep",
                "--why=Downloading Instagram posts", "--mode=block", "sleep", "infinity"]
    return None


@contextmanager
def keep_awake(log: Callable[[str], None] = lambda _m: None) -> Iterator[bool]:
    """Hold off sleep inside the `with` block. Yields True if it worked.

    On Windows, enter and leave it on the same thread (the one downloading).
    """
    if sys.platform == "win32":
        ok = _windows_set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        if not ok:
            log("Couldn't stop Windows from sleeping during the download.")
        try:
            yield ok
        finally:
            if ok:
                _windows_set(ES_CONTINUOUS)  # back to normal: sleep is allowed again
        return

    command = awake_command(sys.platform, os.getpid())
    proc = None
    if command:
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except OSError:
            proc = None
    if proc is None:
        log("Couldn't stop the computer from sleeping during the download; "
            "change its power settings if it goes to sleep.")
    try:
        yield proc is not None
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
