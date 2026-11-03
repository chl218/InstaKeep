# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

InstaKeep keeps a list of public Instagram profiles and downloads each one's newest posts, either from a tkinter window or headlessly. It's built on instaloader and has no login, so only public profiles work.

## Commands

Windows paths shown; on macOS/Linux use `.venv/bin/python`.

```powershell
python instakeep.py                      # window. First start offers to create .venv + pip install -e ., then relaunches inside it
python instakeep.py --run                # download for every saved user, no window (logs to logs/run-YYYY-MM-DD.log)
python instakeep.py --check              # setup status
python instakeep.py --list | --add NAME... | --remove NAME...
.venv\Scripts\igdl USERNAME [--limit N] [--videos] [--caption] [--metadata]   # one-off single profile

.venv\Scripts\pip install -e .[dev]         # deps + pytest
.venv\Scripts\python -m pytest              # all tests (pythonpath=src is set in pyproject.toml)
.venv\Scripts\python -m pytest tests/test_store.py::test_remove
.venv\Scripts\python -m pytest -k rate_limit
```

CI (`.github/workflows/tests.yml`) runs the whole suite on every pull request and every push to `main`, on Windows, Linux (under `xvfb`) and macOS with Python 3.10 and 3.14. There is no linter or formatter configured. Tests never touch the network: Instagram access is replaced with fakes. Tests are headless: `tests/conftest.py` hides every Tk window, records message boxes and file dialogs in the `dialogs` fixture instead of showing them, and points `instakeep.paths` (data, logs, lock, downloads) at the temp folder. Window tests in `tests/test_gui.py` share one session Tk root and give each test its own hidden `Toplevel`. Creating many `tk.Tk()` roots in one process fails on Windows.

## Architecture

There are two packages under `src/`, and dependencies only go one way: `instakeep` → `igdl`. Never the reverse.

- **`igdl`** is the download library plus the `igdl` console script. `downloader.build_loader()` configures instaloader (file naming, images-only default, rate-limit pause notices and stop-during-pause through `_PauseAwareRateController`). `downloader.download_user()` runs the per-profile loop: it drops videos before counting, and reads `limit + 3` posts to handle up to 3 pinned posts. `downloader.download_single_post()` saves one post (shortcode from `security.parse_post_url()`) into the owner's folder with the same file names. `cli.describe_error()` maps instaloader exceptions to `(exit_code, message)`; the CLI and the app both use it. `tags.py` writes caption hashtags into JPEG EXIF `XPKeywords` with piexif, without re-encoding the image.
- **`instakeep`** is the app. `instakeep.py` → `bootstrap.ensure_ready()` → a `store.Store` → one of: `gui.App`, `runner.run_headless()` (`--run`), or the list commands.

Constraints that span several files:

- **Stdlib-only until setup passes.** Before `ensure_ready()` returns, `instakeep.py` imports only `igdl.security`, `instakeep.__init__`, `bootstrap` and `paths`. Those modules must stay standard-library only: no instaloader or piexif, and no other `igdl` module. Everything else is imported after the check. `ensure_ready()` re-launches the script inside `.venv` when one exists.
- **Errors.** Known instaloader errors become one line through `cli.describe_error()`. Unexpected errors keep their traceback: `igdl` re-raises, `instakeep.py`'s `run()` re-raises (and copies it into the `--run` log first). The window worker, Tk callbacks and `--run` show `igdl.security.describe_unexpected()`, which is a summary line plus the full traceback.
- **Timing and estimates.** `downloader.DownloadStats` measures one user's run: per-post time split between images and videos by file count, posts already on disk excluded, rate-limit pauses subtracted. `_PauseAwareRateController` is always installed and counts requests and paused seconds. `runner.run_all` adds each run to the user's `stats` in the store (`store.STAT_FIELDS`; `media_count` and `last_*` are replaced, the rest summed). `instakeep/estimate.py` is pure functions over those records, plus instaloader's limit (`QUERY_LIMIT` per `QUERY_WINDOW`).
- **The window and `--run` are separate processes sharing `data/instakeep.json`.**
  - `Store._mutate()` re-reads the file, applies the change, then writes atomically (temp file + `os.replace`), so neither process overwrites the other's results.
  - `runner.RunLock` (`data/run.lock`, PID + staleness check) stops both from downloading at once.
  - `Store._clean()` validates every setting against `default_settings()` and drops unknown keys. A new setting must be added there, or it's discarded on load.
- **`runner.run_all()` is shared by the window and `--run`.**
  - One user failing doesn't stop the others.
  - A rate-limit error (exit code 4) ends the whole run.
  - It takes injectable `build_loader` / `download_user` / `describe_error`; `tests/test_runner.py` passes fakes through these.
- **GUI threading.** Downloads run on a worker thread that never touches widgets. It posts tuples (`"log"`, `"pause"`, `"user_done"`, `"done"`) to `App.messages`, which `_poll_messages()` drains on the Tk thread every 100 ms. Keep tkinter variables out of the worker; read them into plain values first.
- **Untrusted input.**
  - Every username goes through `igdl.security.is_valid_username` before it's used as a request or folder name. The saved list stores names lowercase (`store.normalize_username`).
  - Any text that can come from Instagram, such as captions or error messages, goes through `strip_control()` before it's printed or shown.
- **Paths** in `instakeep/paths.py` are absolute, based on the file's location, so the program works from any working directory. `data/`, `logs/`, `downloads/` and `.venv/` are created at runtime and git-ignored.
- `igdl.__version__` must stay in sync with `pyproject.toml`.

`--run` exit codes: 0 ok, 1 some user failed (or a bug, with traceback), 3 setup incomplete, 4 rate-limited, 5 another download running, 130 Ctrl+C. `igdl` exit codes: 0, 1 not found, 2 private, 4 rate-limited, 130 Ctrl+C (a bug exits 1 with a traceback).

Python style and the rules a change must keep (errors, untrusted input, rate limits, threads, tests, dependencies) are in [memory/python/CLAUDE.md](memory/python/CLAUDE.md).
