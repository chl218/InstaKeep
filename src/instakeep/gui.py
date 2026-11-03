"""The InstaKeep window (tkinter, standard library only).

Two tabs: Batch downloads the saved users' newest posts; Individual downloads
one post from its link. The download options, Stop, the log and the status
line below the tabs are shared, and only one download runs at a time.

Downloads run on a background thread that never touches widgets: tkinter isn't
thread-safe. The thread sends messages through self.messages, which
_poll_messages() reads on the main thread every POLL_MS milliseconds:
  ("log", text)            add a line to the log box
  ("pause", seconds)       Instagram rate-limit pause started
  ("user_start", name)     one user started: its timer starts ticking
  ("user_done", result)    one user finished: refresh its row
  ("post_owner", name, add) single post: its account is known; add=True adds it to the list
  ("done", text, ok)       the whole run finished
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from tkinter import font as tkfont

from igdl import cli, downloader
from igdl.security import describe_unexpected, parse_post_url, strip_control

from . import paths, runner
from .estimate import QUERY_LIMIT, QUERY_WINDOW, estimate, format_duration
from .store import Store

POLL_MS = 100  # how often the window checks for messages from the download thread
CELL_PADDING = 24  # pixels left and right of the text in a table cell
ROW_PADDING = 12   # pixels above and below the text in a table row

# User table columns: heading, the widest text expected (sets the minimum width,
# measured in the real font so it scales with the screen), and alignment.
COLUMNS = {
    "user": ("Username", "a_long_instagram_name", "w"),
    "last": ("Last download", "2026-12-31 23:59", "w"),
    "result": ("Result", "rate-limited", "w"),
    "count": ("Downloaded", "999999", "e"),
    "time": ("Time", "59 min 59 s", "e"),
    "longest": ("Longest", "99 h 59 min", "e"),
    "total": ("Total time", "999 h 59 min", "e"),
    "images": ("Images", "999999", "e"),
    "videos": ("Videos", "999999", "e"),
}
TITLE = "InstaKeep"
SELECT_FIRST = "Select one or more users in the list first."
MIN_HEIGHT = 700


def format_last(user: dict) -> str:
    """'2026-11-02 08:00' for the 'Last download' column."""
    if not user.get("last_run"):
        return "never"
    try:
        return datetime.fromisoformat(user["last_run"]).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return user["last_run"]


def format_result(user: dict) -> str:
    """'ok', 'stopped', 'not found'... for the 'Result' column.

    The saved status also has the count ('ok, 3 new'); that has its own column.
    """
    return (user.get("last_status") or "").split(",")[0].strip()


def format_estimate(label: str, users: list[dict], settings: dict) -> str:
    """'All 3 users: about 2 min (1 min 40 s downloading + 20 s rate-limit pauses)'."""
    if not users:
        return f"{label}: nothing to download."
    est = estimate(users, settings)
    if not est.users:
        return f"{label}: no estimate yet, none of them has been downloaded before."
    text = (f"{label}: about {format_duration(est.total_seconds)} "
            f"({format_duration(est.download_seconds)} downloading"
            f" + {format_duration(est.pause_seconds)} rate-limit pauses)")
    if est.worst_seconds > est.total_seconds + 1:
        text += f", up to {format_duration(est.worst_seconds)} if every post is new"
    if est.unknown:
        text += f". Post count not known yet for {len(est.unknown)} user(s)"
    if est.no_data:
        text += f". Not counted: {len(est.no_data)} user(s) never downloaded"
    return text + "."


class App:
    """The main window. All widget access happens on the Tk (main) thread."""

    def __init__(self, root: tk.Tk, store: Store) -> None:
        self.root = root
        self.store = store
        self.messages: queue.Queue = queue.Queue()
        self.stop_requested = threading.Event()
        self.worker: threading.Thread | None = None
        self.paused = False  # True while the status line shows a rate-limit pause
        # The user being downloaded and when they started (for the live timer).
        self.timing: tuple[str, float] | None = None
        self.post_owner: str | None = None  # account of the last single post (Open folder)

        # A bug in a button handler: also show its traceback in the log box.
        root.report_callback_exception = self._on_callback_error
        root.title(f"{TITLE} - Save it or lose it")
        root.minsize(760, MIN_HEIGHT)  # widened by _fit_columns() to fit the table

        # Form values. tkinter variables are bound to the widgets built below.
        s = store.settings
        self.new_user = tk.StringVar()
        self.limit = tk.StringVar(value=str(s["limit"]))
        self.all_posts = tk.BooleanVar(value=s["all_posts"])
        self.videos = tk.BooleanVar(value=s["videos"])
        self.caption = tk.BooleanVar(value=s["caption"])
        self.tags = tk.BooleanVar(value=s["tags"])
        self.metadata = tk.BooleanVar(value=s["metadata"])
        self.output_dir = tk.StringVar(value=s["output_dir"])
        self.post_link = tk.StringVar()
        self.add_owner = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready.")
        self.estimate_all = tk.StringVar()
        self.estimate_selected = tk.StringVar()

        self._build_widgets()
        self._refresh_states()
        self._refresh_table()
        # Save option changes as soon as they happen.
        for var in (self.all_posts, self.videos, self.caption, self.tags, self.metadata):
            var.trace_add("write", lambda *_: self._save_settings())
        self.limit.trace_add("write", lambda *_: self._save_settings())
        self.output_dir.trace_add("write", lambda *_: self._save_settings())

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(POLL_MS, self._poll_messages)

    # ------------------------------------------------------------------ layout

    def _build_widgets(self) -> None:
        """Lay out the window: the Batch and Individual tabs, then the shared
        download options, Stop / Open folder, log and status line."""
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=12)
        main.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        # Roomier tab labels. Sized from the font so the padding grows with screen scaling.
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self.root).configure("TNotebook.Tab", padding=(line // 2, line // 6))
        self.tabs = ttk.Notebook(main)
        self.tabs.grid(row=0, column=0, sticky="nsew", **pad)
        main.rowconfigure(0, weight=1)
        batch = ttk.Frame(self.tabs, padding=4)
        batch.columnconfigure(0, weight=1)
        self.tabs.add(batch, text="Batch")
        individual = ttk.Frame(self.tabs, padding=8)
        individual.columnconfigure(1, weight=1)
        self.tabs.add(individual, text="Individual")
        self._build_batch_tab(batch, pad)
        self._build_individual_tab(individual)

        # Download options shared by both tabs.
        opts = ttk.LabelFrame(main, text="Download options", padding=8)
        opts.grid(row=1, column=0, sticky="ew", **pad)
        opts.columnconfigure(1, weight=1)
        kinds = ttk.Frame(opts)
        kinds.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(kinds, text="Videos", variable=self.videos).grid(row=0, column=0, padx=(0, 8))
        ttk.Checkbutton(kinds, text="Caption (.txt)", variable=self.caption).grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(kinds, text="#tags", variable=self.tags).grid(row=0, column=2, padx=(0, 8))
        ttk.Checkbutton(kinds, text="Metadata", variable=self.metadata).grid(row=0, column=3)
        ttk.Label(opts, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(opts, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        ttk.Button(opts, text="Browse…", command=self._pick_output_dir).grid(row=1, column=2, pady=(6, 0))

        buttons = ttk.Frame(main)
        buttons.grid(row=2, column=0, sticky="w", **pad)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Open folder", command=self._open_folder).grid(row=0, column=1)

        # Log + status line.
        self.log_box = scrolledtext.ScrolledText(main, height=8, wrap="word", state="disabled")
        self.log_box.grid(row=3, column=0, sticky="nsew", **pad)
        main.rowconfigure(3, weight=1)
        ttk.Label(main, textvariable=self.status).grid(row=4, column=0, sticky="w", **pad)

    def _build_batch_tab(self, main: ttk.Frame, pad: dict) -> None:
        """The saved users: table, add/remove, how many posts, estimate, run buttons."""
        # User table. Last download, Result, Downloaded and Time describe the latest
        # run ("Time" ticks while a user downloads). Longest is the slowest run;
        # Total time, Images and Videos add up every download of that user.
        table = ttk.Frame(main)
        table.grid(row=0, column=0, sticky="nsew", **pad)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        # ttk's default row height is a fixed pixel count that doesn't grow with the
        # screen's scaling, so on high-DPI screens it cuts off the bottom of the text
        # ("j", "g", "_"). Size rows from the font's real line height instead.
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self.root).configure("Treeview", rowheight=line + ROW_PADDING)
        self.tree = ttk.Treeview(table, columns=tuple(COLUMNS), show="headings", height=8)
        for key, (heading, _sample, anchor) in COLUMNS.items():
            self.tree.heading(key, text=heading)
            self.tree.column(key, anchor=anchor, stretch=key in ("user", "result"))
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_estimate())
        main.rowconfigure(0, weight=1)

        # Add / remove.
        edit = ttk.Frame(main)
        edit.grid(row=1, column=0, sticky="ew", **pad)
        ttk.Label(edit, text="Username:").grid(row=0, column=0, padx=(0, 4))
        entry = ttk.Entry(edit, textvariable=self.new_user, width=28)
        entry.grid(row=0, column=1, padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._add_user())
        entry.focus_set()
        ttk.Button(edit, text="Add", command=self._add_user).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(edit, text="Remove selected", command=self._remove_selected).grid(row=0, column=3)

        # How many posts per user. "Download all posts" greys out the "Newest N" box.
        lim = ttk.Frame(main)
        lim.grid(row=2, column=0, sticky="w", **pad)
        ttk.Checkbutton(lim, text="Download all posts", variable=self.all_posts,
                        command=self._refresh_states).grid(row=0, column=0, padx=(0, 12))
        self.newest_label = ttk.Label(lim, text="Newest")
        self.newest_label.grid(row=0, column=1)
        self.limit_box = ttk.Spinbox(lim, from_=1, to=1000, width=5, textvariable=self.limit)
        self.limit_box.grid(row=0, column=2, padx=4)
        self.posts_label = ttk.Label(lim, text="posts per user")
        self.posts_label.grid(row=0, column=3, padx=(0, 12))

        # Estimated download time, from earlier downloads and the rate limit.
        est = ttk.LabelFrame(main, text="Estimated download time", padding=8)
        est.grid(row=3, column=0, sticky="ew", **pad)
        est.columnconfigure(0, weight=1)
        labels = [
            ttk.Label(est, textvariable=self.estimate_all, justify="left"),
            ttk.Label(est, textvariable=self.estimate_selected, justify="left"),
            ttk.Label(est, foreground="gray", justify="left", text=(
                f"Based on each user's earlier downloads (users never downloaded are left out). "
                f"Pauses: instaloader allows about {QUERY_LIMIT} Instagram requests per "
                f"{QUERY_WINDOW // 60} minutes, and Instagram may block for longer.")),
        ]
        for row, label in enumerate(labels):
            label.configure(wraplength=600)  # until the window knows its width (see below)
            label.grid(row=row, column=0, sticky="w", pady=(4, 0) if row == 2 else 0)
        # Wrap the text at the section's current width, so it follows the window.
        est.bind("<Configure>", lambda e: [lb.configure(wraplength=max(200, e.width - 24))
                                           for lb in labels])

        # Run buttons.
        buttons = ttk.Frame(main)
        buttons.grid(row=4, column=0, sticky="w", **pad)
        self.all_button = ttk.Button(buttons, text="Download all", command=lambda: self._start(None))
        self.all_button.grid(row=0, column=0, padx=(0, 6))
        self.sel_button = ttk.Button(buttons, text="Download selected", command=self._start_selected)
        self.sel_button.grid(row=0, column=1)

    def _build_individual_tab(self, tab: ttk.Frame) -> None:
        """One post from its link, optionally adding its account to the saved list."""
        ttk.Label(tab, text="Post link:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        entry = ttk.Entry(tab, textvariable=self.post_link)
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._start_post())
        self.post_button = ttk.Button(tab, text="Download post", command=self._start_post)
        self.post_button.grid(row=0, column=2)
        ttk.Checkbutton(tab, text="Also add the post's account to the saved list (Batch tab)",
                        variable=self.add_owner).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        hint = ttk.Label(tab, foreground="gray", justify="left", text=(
            "Paste a link to a post or reel, e.g. https://www.instagram.com/p/… "
            "It's saved in the output folder under the account's name, so a Batch "
            "download of that account skips it. Public accounts only."))
        hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tab.bind("<Configure>", lambda e: hint.configure(wraplength=max(200, e.width - 24)))

    # -------------------------------------------------------------- user list

    def _refresh_table(self) -> None:
        """Redraw the user table from the store, keeping the selection."""
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for user in self.store.users:
            name, st = user["username"], user["stats"]
            ran = bool(user.get("last_run"))
            self.tree.insert("", "end", iid=name, values=(
                name, format_last(user), format_result(user),
                st["last_images"] + st["last_videos"] if ran else "",
                format_duration(st["last_seconds"]) if ran else "",
                format_duration(st["longest_seconds"]) if st["longest_seconds"] else "",
                format_duration(st["seconds"]) if st["seconds"] else "",
                st["images"], st["videos"],
            ))
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        self._tick_timer()        # the running user's row was just redrawn
        self._fit_columns()
        self._refresh_estimate()

    def _fit_columns(self) -> None:
        """Make every column wide enough for its heading and text, and the window for the table.

        Widths are measured in the fonts the table really uses, so nothing is cut
        off on high-DPI screens where text is larger than a fixed pixel width.
        """
        cell_font = tkfont.nametofont("TkDefaultFont")
        heading_font = tkfont.nametofont("TkHeadingFont")
        rows = [self.tree.item(iid)["values"] for iid in self.tree.get_children()]
        total = 0
        for i, (key, (heading, sample, _anchor)) in enumerate(COLUMNS.items()):
            texts = [sample] + [str(row[i]) for row in rows if i < len(row)]
            width = max([heading_font.measure(heading)] + [cell_font.measure(t) for t in texts])
            width += CELL_PADDING
            self.tree.column(key, width=width, minwidth=width)
            total += width
        # Table + scrollbar + the frame and grid padding around it.
        self.root.minsize(total + 80, MIN_HEIGHT)

    def _refresh_estimate(self) -> None:
        """Recompute both estimate lines (all users, and the selected ones)."""
        settings = self._form_settings()
        users = self.store.users
        self.estimate_all.set(format_estimate(f"All {len(users)} user(s)", users, settings))
        chosen = set(self.tree.selection())
        if chosen:
            picked = [u for u in users if u["username"] in chosen]
            self.estimate_selected.set(format_estimate(f"Selected ({len(picked)})", picked, settings))
        else:
            self.estimate_selected.set("Select users in the list to estimate just those.")

    def _tick_timer(self) -> None:
        """Show the running user's elapsed time in their "Time" cell."""
        if self.timing and self.tree.exists(self.timing[0]):
            name, started = self.timing
            self.tree.set(name, "time", format_duration(time.monotonic() - started))

    def _add_user(self) -> None:
        """Add the name in the entry box (the store validates it)."""
        text = self.new_user.get()
        if not text.strip():
            return
        try:
            added = self.store.add_user(text)
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e), parent=self.root)
            return
        self.new_user.set("")
        self._refresh_table()
        self.status.set("Added." if added else "Already in the list.")

    def _selected_names(self) -> list[str]:
        """The selected usernames. Shows a hint and returns [] if none are selected."""
        names = list(self.tree.selection())
        if not names:
            messagebox.showinfo(TITLE, SELECT_FIRST, parent=self.root)
        return names

    def _remove_selected(self) -> None:
        """Remove the selected users after asking. Their files stay on disk."""
        names = self._selected_names()
        if not names:
            return
        listed = ", ".join(f"@{n}" for n in names)
        if not messagebox.askyesno(TITLE, f"Remove {listed} from the list?\n\n"
                                   "Downloaded files are kept.", parent=self.root):
            return
        for name in names:
            self.store.remove_user(name)
        self._refresh_table()
        self.status.set(f"Removed {len(names)} user(s).")

    # --------------------------------------------------------------- settings

    def _refresh_states(self) -> None:
        """Grey out "Newest N posts per user" while "Download all posts" is ticked."""
        state = "disabled" if self.all_posts.get() else "normal"
        for widget in (self.newest_label, self.limit_box, self.posts_label):
            widget.configure(state=state)

    def _form_settings(self) -> dict:
        """The settings as the form shows them (half-typed values fall back to saved ones)."""
        s = self.store.settings
        s.update(all_posts=self.all_posts.get(), videos=self.videos.get())
        s["limit"] = self._read_limit() or s["limit"]
        return s

    def _read_limit(self) -> int | None:
        """The posts-per-user box as a number, or None if it isn't 1 or more."""
        try:
            limit = int(self.limit.get())
        except ValueError:
            return None
        return limit if limit >= 1 else None

    def _save_settings(self) -> None:
        """Save the options. Runs on every change, so it skips half-typed values."""
        values = {"all_posts": self.all_posts.get(), "videos": self.videos.get(),
                  "caption": self.caption.get(), "tags": self.tags.get(),
                  "metadata": self.metadata.get()}
        limit = self._read_limit()
        if limit is not None:  # half-typed number: keep the saved value
            values["limit"] = limit
        if self.output_dir.get().strip():
            values["output_dir"] = self.output_dir.get().strip()
        self.store.update_settings(**values)
        self._refresh_estimate()

    def _pick_output_dir(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_dir.get() or str(paths.APP_DIR))
        if folder:
            self.output_dir.set(folder)

    # -------------------------------------------------------------- run / stop

    def _start_selected(self) -> None:
        names = self._selected_names()
        if names:
            self._start(names)

    def _start(self, only: list[str] | None) -> None:
        """Start downloading for `only` (None = every user) on the worker thread."""
        if self.worker and self.worker.is_alive():
            return  # already running
        if not self.store.usernames():
            messagebox.showinfo(TITLE, "Add a user to the list first.", parent=self.root)
            return
        if not self.all_posts.get() and self._read_limit() is None:
            messagebox.showwarning(TITLE, "The number of posts must be 1 or more.", parent=self.root)
            return
        self._launch(self._run, only)

    def _start_post(self) -> None:
        """Download the post in the Individual tab's link box on the worker thread."""
        if self.worker and self.worker.is_alive():
            return  # already running
        try:
            shortcode = parse_post_url(self.post_link.get())
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e), parent=self.root)
            return
        self._save_settings()
        # Plain values for the worker: it must not read tkinter variables.
        self._launch(self._run_post, shortcode, self.add_owner.get(), self.store.settings)

    def _launch(self, target, *args) -> None:
        """Start `target(*args)` on the worker thread with a fresh log."""
        self._clear_log()
        self.stop_requested.clear()
        self._set_running(True)
        self.status.set("Downloading…")
        # daemon=True: closing the window ends the program even mid-download.
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _set_running(self, running: bool) -> None:
        for button in (self.all_button, self.sel_button, self.post_button):
            button.configure(state="disabled" if running else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _stop(self) -> None:
        # Checked before each post (the current post finishes first) and every
        # half second during a rate-limit pause.
        self.stop_requested.set()
        self.status.set("Stopping after the current post…")
        self.stop_button.configure(state="disabled")

    def _run(self, only: list[str] | None) -> None:
        """Runs on the worker thread. Every outcome ends with one ("done", ...) message,
        so the buttons are always re-enabled, even after an unexpected error."""
        put = self.messages.put
        lock = runner.RunLock(paths.LOCK_FILE)
        try:
            if not lock.acquire():
                put(("done", "Another download (another window or a --run) is in progress. "
                     "Try again later.", False))
                return
            results = runner.run_all(
                self.store,
                log=lambda text: put(("log", text)),
                should_stop=self.stop_requested.is_set,
                on_pause=lambda secs: put(("pause", secs)),
                on_user_done=lambda r: put(("user_done", r)),
                on_user_start=lambda name: put(("user_start", name)),
                only=only,
            )
            ok = sum(r.ok for r in results)
            new = sum(r.new_files for r in results)
            put(("done", f"Done. {ok}/{len(results)} user(s) OK, {new} new file(s).", True))
        except Exception as e:  # noqa: BLE001 - every failure must reach the window
            put(("done", describe_unexpected(e), False))
        finally:
            lock.release()

    def _run_post(self, shortcode: str, add_owner: bool, settings: dict,
                  build_loader=downloader.build_loader,
                  download_post=downloader.download_single_post) -> None:
        """Runs on the worker thread: download one post. Like _run(), every outcome
        ends with one ("done", ...) message. Tests pass fake build_loader/download_post."""
        put = self.messages.put
        log = lambda text: put(("log", text))  # noqa: E731 - short local callback
        lock = runner.RunLock(paths.LOCK_FILE)
        try:
            if not lock.acquire():
                put(("done", "Another download (another window or a --run) is in progress. "
                     "Try again later.", False))
                return
            loader = build_loader(
                Path(settings["output_dir"]), videos=settings["videos"], caption=settings["caption"],
                metadata=settings["metadata"], quiet=True,
                on_pause=lambda secs: put(("pause", secs)), should_stop=self.stop_requested.is_set,
            )
            loader.context.error = lambda msg, repeat_at_end=True: log(f"warning: {msg}")
            result = download_post(loader, shortcode, log=log, tags=settings["tags"])
            put(("post_owner", result.owner, add_owner))
            if not result.saved:
                put(("done", "Nothing downloaded: the post is a video.", True))
            else:
                put(("done", f"Done. {result.new_files} new file(s) from @{result.owner}.", True))
        except downloader.DownloadStopped:
            put(("done", "Stopped.", True))
        except Exception as e:  # noqa: BLE001 - every failure must reach the window
            known = cli.describe_error(e, "", post=shortcode)
            put(("done", known[1] if known else describe_unexpected(e), False))
        finally:
            lock.release()

    # --------------------------------------------------- main-thread plumbing

    def _poll_messages(self) -> None:
        """Handle everything the worker thread sent since the last check."""
        try:
            while True:
                msg = self.messages.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                    if self.paused:  # new progress means the pause is over
                        self.paused = False
                        self.status.set("Downloading…")
                elif kind == "pause":
                    text = downloader.format_pause(msg[1])
                    self._append_log(text)
                    self.paused = True
                    self.status.set(text + " Press Stop to cancel.")
                elif kind == "user_start":
                    self.timing = (msg[1], time.monotonic())
                elif kind == "user_done":
                    self.timing = None
                    self.store.reload()  # the worker recorded this user's result and times
                    self._refresh_table()
                elif kind == "post_owner":
                    self._on_post_owner(msg[1], msg[2])
                elif kind == "done":
                    _, text, ok = msg
                    self.paused = False
                    self.timing = None
                    self._append_log(text if ok else f"error: {text}")
                    self.status.set(text.splitlines()[0] if ok else "Failed. See the log above.")
                    self._set_running(False)
                    self.store.reload()
                    self._refresh_table()
                    if not ok:
                        self._show_error(text)
        except queue.Empty:
            pass
        self._tick_timer()
        self.root.after(POLL_MS, self._poll_messages)

    def _on_post_owner(self, owner: str, add: bool) -> None:
        """A single post's account is known: remember it, and add it to the list if asked."""
        self.post_owner = owner
        if not add:
            return
        try:
            added = self.store.add_user(owner)
        except ValueError as e:  # download_single_post already checked it; just in case
            self._append_log(f"Couldn't add @{owner}: {e}")
            return
        self._append_log(f"Added @{owner} to the saved list." if added
                         else f"@{owner} is already in the saved list.")
        self._refresh_table()

    def _append_log(self, text: str) -> None:
        # Log text can come from Instagram (captions, errors): strip control characters.
        self.log_box.configure(state="normal")
        self.log_box.insert("end", strip_control(str(text)) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _open_folder(self) -> None:
        """Open a user's folder (or the output folder) in the file manager.

        Batch tab: the selected user's. Individual tab: the last downloaded post's account.
        """
        # resolve(): an absolute path can't be mistaken for an option by open/xdg-open.
        base = Path(self.output_dir.get().strip() or paths.DEFAULT_OUTPUT).resolve()
        if self.tabs.index("current") == 1:
            name = self.post_owner
        else:
            selected = self.tree.selection()
            name = selected[0] if selected else None
        folder = base / name if name and (base / name).is_dir() else base
        if not folder.is_dir():
            messagebox.showinfo(TITLE, f"{folder} doesn't exist yet. Download something first.",
                                parent=self.root)
            return
        if sys.platform == "win32":
            # Safe because folder.is_dir() was checked: startfile on a file would run it.
            os.startfile(folder)  # noqa: S606 - opens Explorer on a local folder
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(folder)], check=False)

    def _on_callback_error(self, exc_type, exc, tb) -> None:
        """Tk calls this when a button or timer handler raises.

        The traceback goes to the console (as Tk does by default) and to the log box.
        """
        tk.Tk.report_callback_exception(self.root, exc_type, exc, tb)
        text = describe_unexpected(exc)
        self._append_log(f"error: {text}")
        self._show_error(text)

    def _show_error(self, text: str) -> None:
        """Error dialog with the first line; a traceback stays in the log box."""
        first, _, rest = strip_control(text).partition("\n")
        messagebox.showerror(TITLE, first + ("\n\nThe log has the details." if rest else ""),
                             parent=self.root)

    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(TITLE, "A download is running. Quit anyway?", parent=self.root):
                return
            self.stop_requested.set()
        self.root.destroy()


def main(store: Store) -> int:
    """Open the window and run until it's closed."""
    if sys.platform == "win32":
        # Sharp text on high-DPI screens instead of blurry scaled-up pixels.
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root, store)
    root.mainloop()
    return 0
