#!/usr/bin/env python3
"""InstaKeep: download the newest posts of a saved list of Instagram users.

Run it from anywhere:
    python instakeep.py              open the window
    python instakeep.py --run        download for every saved user, no window
    python instakeep.py --check      show the setup status
    python instakeep.py --list | --add NAME | --remove NAME

On first start it checks its setup and, after asking, creates .venv and installs
InstaKeep's dependencies (instaloader, piexif) into it. Only the standard library is used before that.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "src"))

# Only standard-library modules can be imported here: setup hasn't checked yet
# whether instaloader and piexif are installed. igdl.security is stdlib-only.
from igdl.security import describe_unexpected, normalize_username, safe_console, strip_control  # noqa: E402
from instakeep import __version__, bootstrap, paths  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    """The command-line options. With none, the window opens."""
    p = argparse.ArgumentParser(
        prog="instakeep.py",
        description="Download the newest posts of a saved list of Instagram users.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="download for every saved user without a window")
    mode.add_argument("--check", action="store_true", help="show the setup status and exit")
    mode.add_argument("--list", action="store_true", help="print the saved users")
    mode.add_argument("--add", metavar="NAME", nargs="+", help="add users to the list")
    mode.add_argument("--remove", metavar="NAME", nargs="+", help="remove users from the list")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def _write_log_line(text: str) -> None:
    """Append to today's --run log (logs/run-YYYY-MM-DD.log). Never fails."""
    try:
        paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(paths.LOGS_DIR / f"run-{datetime.now():%Y-%m-%d}.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S} {text}\n")
    except OSError:
        pass


def _headless_say(text: str) -> None:
    """Setup messages for --run: pythonw has no console, so also write them to the log."""
    _write_log_line(f"setup: {text}")
    if sys.stderr is not None:
        print(text, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    """Check the setup, then run the chosen mode. Returns the exit code."""
    argv = sys.argv[1:] if argv is None else argv
    safe_console()
    args = parse_args(argv)

    if args.check:
        # Report on the Python the program would really use: the venv, if there is one.
        venv_py = bootstrap.venv_python(paths.VENV)
        if venv_py.exists() and not bootstrap.in_venv(paths.VENV):
            return bootstrap.relaunch(venv_py, argv)
        ok, text = bootstrap.report()
        print(text)
        return 0 if ok else bootstrap.EXIT_SETUP

    gui = not (args.run or args.list or args.add or args.remove)
    if args.run:
        code = bootstrap.ensure_ready(argv, ask=None, need_tk=False, say=_headless_say)
    else:
        code = bootstrap.ensure_ready(argv, ask="gui" if gui else "console", need_tk=gui)
    if code is not None:
        return code

    # Setup is fine: igdl and its dependencies can be imported from here on.
    from instakeep.store import Store
    store = Store(paths.STORE_FILE, paths.DEFAULT_OUTPUT)

    if args.run:
        from instakeep import runner
        return runner.run_headless(store)
    if args.list:
        for user in store.users:
            print(f"{user['username']:<32} {user['last_run'] or 'never'}  {user['last_status'] or ''}")
        return 0
    if args.add:
        code = 0
        for name in args.add:
            try:
                clean = normalize_username(name)
                print(("added " if store.add_user(clean) else "already listed ") + clean)
            except ValueError as e:
                print(f"{strip_control(name)}: {e}", file=sys.stderr)
                code = 2
        return code
    if args.remove:
        for name in args.remove:
            print(("removed " if store.remove_user(name) else "not listed ") + strip_control(name))
        return 0

    from instakeep import gui as window
    return window.main(store)


def run(argv: list[str] | None = None) -> int:
    """main(), with a short message for Ctrl+C.

    Any other error keeps Python's full traceback. A --run also writes it to
    the log, because pythonw has no console to show it on.
    """
    argv = sys.argv[1:] if argv is None else argv
    try:
        return main(argv)
    except KeyboardInterrupt:
        if sys.stderr is not None:
            print("\nInterrupted. Files saved so far are kept.", file=sys.stderr)
        return 130  # the usual shell convention: 128 + SIGINT
    except Exception as e:
        if "--run" in argv:
            _write_log_line(f"error: {describe_unexpected(e)}")
        raise


if __name__ == "__main__":
    sys.exit(run())
