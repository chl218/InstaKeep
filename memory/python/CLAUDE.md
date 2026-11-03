# Python guidelines for InstaKeep

How Python is written in this repo. The architecture and commands are in the root `CLAUDE.md`. This file covers style and the rules a change has to keep.

## Style

- Start every module with `from __future__ import annotations`. Use `X | None` and built-in generics (`list[str]`, `dict`). Python 3.10 is the minimum.
- Give every function signature type hints. Use `Callable[[str], None]` for callbacks such as `log`, `should_stop` and `on_pause`.
- Use plain functions by default. Use a class only when there is state to hold: `Store`, `RunLock`, `App`, or instaloader subclasses. Use `@dataclass` for result records like `runner.UserResult`.
- Keep side-effect-free helpers apart from the code that calls the system. Pure helpers get direct tests. System calls stay thin. Examples are `bootstrap.venv_python()`, `in_venv()` and `cli.positive_int()`.
- Every module starts with a docstring saying what it is for. Comments explain *why*, not what. Keep them short.
- Use guard clauses and early returns, and put the normal path last.
- Use `pathlib.Path` everywhere. Read and write text with an explicit `encoding="utf-8"`.
- Write user-facing messages in plain English. Say what happened and what to do next ("Wait a while and re-run; already-downloaded posts are skipped.").

## Errors

- Map known failures to `(exit_code, message)` in one place: `igdl.cli.describe_error()`. Reuse it rather than writing a new mapping. Exit codes are documented in the README, so don't renumber them.
- Catch broad exceptions only at a boundary where the failure must still reach the user: the GUI worker and Tk callbacks, the `--run` loop, the per-user loop. Mark them `# noqa: BLE001 - <reason>`. Everywhere else, let unexpected errors raise.
- Keep tracebacks for unexpected errors. In the terminal, let them propagate (`igdl`, `instakeep.py`). Where there's no terminal to show them (the window, `--run`), log `igdl.security.describe_unexpected(e)`, which is a summary line plus the traceback, and show only its first line in a dialog.
- Every `noqa` carries a reason (`# noqa: S606 - opens Explorer on a local folder`).
- One user failing never stops the others. A rate-limit or connection error stops the whole run, because the remaining users would be blocked too.

## Untrusted input

Usernames, captions and error text from Instagram are untrusted.

- Validate with `igdl.security.is_valid_username()` before a name is used in a request or a path. That check also rules out `../` tricks.
- Pass anything printed, logged or shown in the window through `strip_control()`, so a caption can't send terminal escape codes.
- Run `subprocess.run` with an argument list only. Never use `shell=True` or build a command string.

## Network and rate limits

- There is no login. Never add credential or session handling without an explicit request.
- Leave rate limiting to instaloader's `RateController`. InstaKeep only makes the pauses visible (`format_pause`) and lets them be stopped (`should_stop`). Never shorten or skip the pauses.
- Long-running loops check `should_stop()` between posts and between users.

## Shared state and threads

- The window and `--run` are separate processes using the same `data/instakeep.json`. Change it only through `Store` methods; they re-read, change and then write atomically. Don't cache settings past one operation, and call `store.reload()` after a run.
- Wrap any download in `runner.RunLock`.
- The tkinter worker thread never touches widgets or `tk.*Var`. Copy values into plain Python objects on the Tk thread, and send results back through the `App.messages` queue.

## Startup constraint

`igdl/security.py`, `instakeep/__init__.py`, `paths.py` and `bootstrap.py` run before the dependencies are known to be installed. In those files, use the standard library only: no instaloader, no piexif, and no other `igdl` module. `instakeep.py` imports everything else only after `ensure_ready()` succeeds.

## Tests

- Use pytest. Tests live in `tests/`, and `pythonpath = ["src"]` is set in `pyproject.toml`.
- Never hit the network. Pass fakes through the injectable parameters (`run_all(build_loader=..., download_user=..., describe_error=...)`), or use `monkeypatch`.
- Use `tmp_path` for every file the code touches. Don't depend on the real `data/`, `logs/` or `downloads/`.
- Keep tests headless. Never show a window or a real dialog: rely on `tests/conftest.py`, and check dialogs with the `dialogs` fixture. In window tests, use the `app` fixture (a hidden `Toplevel`), not a new `tk.Tk()`.
- Test against real JPEGs where EXIF matters (`tests/test_tags.py` builds them with piexif).
- Add or adjust a test whenever behavior changes: settings validation, error mapping, limit and pinned-post handling, tag extraction.

## Dependencies

Runtime dependencies are `instaloader` and `piexif` only. The window is standard-library `tkinter`. Adding a runtime dependency means updating `pyproject.toml`, `bootstrap.REQUIRED_MODULES` and the README setup table. Prefer the standard library.
