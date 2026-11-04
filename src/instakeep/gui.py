"""The InstaKeep window (tkinter, standard library only).

Three tabs: From user downloads the saved users' newest posts; From link downloads
one post from its link; From file reads usernames and post links from a .txt file
(add the usernames to the saved list, download the links). The download
options, Stop, the log and the status line below the tabs are shared, and only
one download runs at a time.

Downloads run on a background thread that never touches widgets: tkinter isn't
thread-safe. The thread sends messages through self.messages, which
_poll_messages() reads on the main thread every POLL_MS milliseconds:
  ("log", text)            add a line to the log box
  ("pause", seconds)       Instagram rate-limit pause started
  ("user_start", name)     one user started: its timer starts ticking
  ("user_done", result)    one user finished: refresh its row
  ("post_owner", name, add) single post: its account is known; add=True adds it to the list
  ("done", text, ok)       the whole run finished
  ("preview", image, path, caption)  a newly saved image, loaded and shrunk off the Tk thread

The right side shows the image downloaded most recently in this session
(preview.py), next to the tabs. Images from before the window opened are never
loaded; "Show preview" hides it for this session (it's on at every start).

If a newer InstaKeep wrote the data file, this window can't save to it (it would
drop fields it doesn't know): downloading and editing the list are turned off,
and the status line asks for a restart. See store.NewerStoreError.
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
from igdl.security import (describe_unexpected, parse_entries, parse_post_url,
                           read_entries_file, strip_control)

from . import awake, paths, runner
from .estimate import QUERY_LIMIT, QUERY_WINDOW, estimate, format_duration
from . import preview
from .store import NewerStoreError, Store

POLL_MS = 100  # how often the window checks for messages from the download thread
CELL_PADDING = 12  # pixels added to the longest text in a table column (both sides together)
ROW_PADDING = 12   # pixels above and below the text in a table row

# User table columns and their headings. Headings are centered and cells
# right-aligned. Each column is as wide as its longest text (see _fit_columns).
COLUMNS = {
    "user": "Username",
    "last": "Last download",
    "result": "Result",
    "count": "Downloaded",
    "time": "Time",
    "longest": "Longest",
    "total": "Total time",
    "images": "Images",
    "videos": "Videos",
}
SORT_UP, SORT_DOWN = " ▲", " ▼"  # added to the heading of the sorted column


def _ran(user: dict) -> bool:
    return bool(user.get("last_run"))


# What each column sorts by: the underlying values, not the shown text, so
# "1 min 15 s" sorts after "45 s". Users never downloaded sort before everyone (-1).
SORT_KEYS = {
    "user": lambda u: u["username"],
    "last": lambda u: u.get("last_run") or "",
    "result": lambda u: format_result(u),
    "count": lambda u: u["stats"]["last_images"] + u["stats"]["last_videos"] if _ran(u) else -1,
    "time": lambda u: u["stats"]["last_seconds"] if _ran(u) else -1,
    "longest": lambda u: u["stats"]["longest_seconds"],
    "total": lambda u: u["stats"]["seconds"],
    "images": lambda u: u["stats"]["images"],
    "videos": lambda u: u["stats"]["videos"],
}


GRID_COLOR = "#d0d0d0"  # the table's cell borders
STRIPE_COLOR = "#e6f0fa"  # light blue, on every other row of the table
STRIPE_TAG = "stripe"


def grid_lines(widths: list[int], rows: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """The table's cell borders as 1-pixel rectangles (x, y, width, height).

    widths: each column's width, left to right. rows: the visible rows' boxes
    (x, y, width, height) from Treeview.bbox, top to bottom. One line under each
    row, and one at the right edge of each column from the first row down, so
    the headings (where columns are resized by dragging) stay uncovered.
    """
    if not rows:
        return []
    left, top = rows[0][0], rows[0][1]
    bottom = rows[-1][1] + rows[-1][3]
    right = left + sum(widths)
    lines = [(left, y + h - 1, right - left, 1) for _x, y, _w, h in rows]
    x = left
    for width in widths:
        x += width
        lines.append((x - 1, top, 1, bottom - top))
    return lines


def _set_wrap(label: ttk.Label, width: int) -> None:
    """Wrap a label's text at `width` pixels (at least 200). Only changes it when
    the width really changed: every change makes Tk lay the window out again."""
    width = max(200, width)
    if int(str(label.cget("wraplength")) or 0) != width:
        label.configure(wraplength=width)


def sort_users(users: list[dict], column: str | None, descending: bool = False) -> list[dict]:
    """The users ordered by a table column (None: the saved list order).
    Ties keep the list order."""
    if column is None:
        return list(users)
    return sorted(users, key=SORT_KEYS[column], reverse=descending)
TITLE = "InstaKeep"
SELECT_FIRST = "Select one or more users in the list first."
SELECT_LINKS_FIRST = "Select one or more links in the list first."
NO_FILE_USERS = "Load a file with usernames first (From file tab)."
NO_FILE_LINKS = "Load a file with post links first (From file tab)."
ALREADY_LISTED = "  (already listed)"
REJECTED_SHOWN = 5  # how many skipped lines the log shows after loading a file
NOTHING_CHOSEN = "Tick Images or Videos (or both) under Download options: there's nothing to download."
MIN_HEIGHT = 700
PREVIEW_LINES = 18  # the preview area's starting size, in text lines (scales with the screen)
NO_IMAGE = "No image yet"


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
        self.store_blocked = False  # True: the data file is from a newer InstaKeep
        # The table's sort: (column, descending), or None for the saved list order.
        self.sort: tuple[str, bool] | None = None
        self.grid_frames: list[tk.Frame] = []  # the drawn cell borders (see _draw_grid)
        self._grid_pending = False
        # Image preview. preview_on is read by the worker thread, so it's an Event.
        self.preview_on = threading.Event()
        self.preview_on.set()
        self.preview_image = None   # the loaded (shrunk) PIL image on show
        self.preview_photo = None   # its Tk PhotoImage; must be kept, or Tk drops it
        self.preview_path: Path | None = None
        self.preview_caption_text = ""
        self.unshown: tuple[Path, str] | None = None  # newest image saved while hidden
        self._fit_pending = False

        # A bug in a button handler: also show its traceback in the log box.
        root.report_callback_exception = self._on_callback_error
        root.title(f"{TITLE} - Save it or lose it")
        root.minsize(760, MIN_HEIGHT)  # widened by _fit_columns() to fit the table

        # Form values. tkinter variables are bound to the widgets built below.
        s = store.settings
        self.new_user = tk.StringVar()
        self.limit = tk.StringVar(value=str(s["limit"]))
        self.all_posts = tk.BooleanVar(value=s["all_posts"])
        self.images = tk.BooleanVar(value=s["images"])
        self.videos = tk.BooleanVar(value=s["videos"])
        self.caption = tk.BooleanVar(value=s["caption"])
        self.tags = tk.BooleanVar(value=s["tags"])
        self.metadata = tk.BooleanVar(value=s["metadata"])
        self.output_dir = tk.StringVar(value=s["output_dir"])
        self.post_link = tk.StringVar()
        self.add_owner = tk.BooleanVar(value=False)
        self.files_path = tk.StringVar()
        self.files_add_owner = tk.BooleanVar(value=False)
        self.files_users: list[str] = []                 # usernames from the loaded file
        self.files_links: list[tuple[str, str]] = []     # (shortcode, link) from the loaded file
        self.status = tk.StringVar(value="Ready.")
        self.estimate_all = tk.StringVar()
        self.estimate_selected = tk.StringVar()
        self.show_preview = tk.BooleanVar(value=True)  # not saved: on at every start

        self._build_widgets()
        self._refresh_states()
        self._refresh_table()
        # Save option changes as soon as they happen.
        for var in (self.all_posts, self.images, self.videos, self.caption, self.tags, self.metadata):
            var.trace_add("write", lambda *_: self._save_settings())
        self.limit.trace_add("write", lambda *_: self._save_settings())
        self.output_dir.trace_add("write", lambda *_: self._save_settings())

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(POLL_MS, self._poll_messages)
        if store.too_new:
            self._block_for_newer_store(str(NewerStoreError(store.path, store.file_version)))

    # ------------------------------------------------------------------ layout

    def _build_widgets(self) -> None:
        """Lay out the window: the From user, From link and From file tabs with the image preview
        to their right, then the shared download options, Stop / Open folder /
        Show preview, log and status line across the full width."""
        pad = {"padx": 8, "pady": 4}
        main = ttk.Frame(self.root, padding=12)
        main.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)

        # Roomier tab labels. Sized from the font so the padding grows with screen scaling.
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(self.root).configure("TNotebook.Tab", padding=(line // 2, line // 6))
        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="nsew")
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)
        self.tabs = ttk.Notebook(top)
        self.tabs.grid(row=0, column=0, sticky="nsew", **pad)
        self.preview_frame = ttk.LabelFrame(top, text="Latest image", padding=8)
        self.preview_frame.grid(row=0, column=1, sticky="nsew", **pad)
        self._build_preview(self.preview_frame, line)
        batch = ttk.Frame(self.tabs, padding=4)
        batch.columnconfigure(0, weight=1)
        self.tabs.add(batch, text="From user")
        individual = ttk.Frame(self.tabs, padding=8)
        individual.columnconfigure(1, weight=1)
        self.tabs.add(individual, text="From link")
        files = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(files, text="From file")
        self._build_batch_tab(batch, pad)
        self._build_individual_tab(individual)
        self._build_files_tab(files)

        # Download options shared by all tabs.
        opts = ttk.LabelFrame(main, text="Download options", padding=8)
        opts.grid(row=1, column=0, sticky="ew", **pad)
        opts.columnconfigure(1, weight=1)
        kinds = ttk.Frame(opts)
        kinds.grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(kinds, text="Images", variable=self.images).grid(row=0, column=0, padx=(0, 8))
        ttk.Checkbutton(kinds, text="Videos", variable=self.videos).grid(row=0, column=1, padx=(0, 8))
        ttk.Checkbutton(kinds, text="Caption (.txt)", variable=self.caption).grid(row=0, column=2, padx=(0, 8))
        ttk.Checkbutton(kinds, text="#tags", variable=self.tags).grid(row=0, column=3, padx=(0, 8))
        ttk.Checkbutton(kinds, text="Metadata", variable=self.metadata).grid(row=0, column=4)
        ttk.Label(opts, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(opts, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
        ttk.Button(opts, text="Browse…", command=self._pick_output_dir).grid(row=1, column=2, pady=(6, 0))

        buttons = ttk.Frame(main)
        buttons.grid(row=2, column=0, sticky="ew", **pad)
        buttons.columnconfigure(2, weight=1)
        self.stop_button = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(buttons, text="Open folder", command=self._open_folder).grid(row=0, column=1)
        ttk.Checkbutton(buttons, text="Show preview", variable=self.show_preview,
                        command=self._toggle_preview).grid(row=0, column=2, sticky="e")

        # Log + status line.
        self.log_box = scrolledtext.ScrolledText(main, height=8, wrap="word", state="disabled")
        self.log_box.grid(row=3, column=0, sticky="nsew", **pad)
        main.rowconfigure(3, weight=1)
        ttk.Label(main, textvariable=self.status).grid(row=4, column=0, sticky="w", **pad)

    def _build_preview(self, frame: ttk.LabelFrame, line: int) -> None:
        """The newest image, a caption (account, date, post) and Open image."""
        side = line * PREVIEW_LINES
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        # A fixed-size area (grid_propagate off), so a new image doesn't resize the window.
        self.preview_area = ttk.Frame(frame, width=side, height=side)
        self.preview_area.grid(row=0, column=0, sticky="nsew")
        self.preview_area.grid_propagate(False)
        self.preview_area.columnconfigure(0, weight=1)
        self.preview_area.rowconfigure(0, weight=1)
        self.preview_label = ttk.Label(self.preview_area, text=NO_IMAGE, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        self.preview_caption = ttk.Label(frame, text="", wraplength=side, justify="left")
        self.preview_caption.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.open_image_button = ttk.Button(frame, text="Open image", command=self._open_image,
                                            state="disabled")
        self.open_image_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        # Refit the image when the panel changes size (window resized).
        self.preview_area.bind("<Configure>", lambda _e: self._schedule_fit(), add="+")

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
        self.tree.tag_configure(STRIPE_TAG, background=STRIPE_COLOR)
        for key, heading in COLUMNS.items():
            # Click a heading to sort by it; click again to reverse.
            self.tree.heading(key, text=heading, anchor="center",
                              command=lambda k=key: self._sort_by(k))
            # stretch=False: a wider window doesn't widen the columns past their text.
            self.tree.column(key, anchor="e", stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        # Treeview can't draw cell borders, so _draw_grid places thin lines over it.
        # Redrawn after scrolling, resizing (window or a dragged column edge) and redrawing rows.
        self.tree.configure(yscrollcommand=lambda *a: (scroll.set(*a), self._schedule_grid()))
        self.tree.bind("<Configure>", lambda _e: self._schedule_grid(), add="+")
        self.tree.bind("<ButtonRelease-1>", lambda _e: self._schedule_grid(), add="+")
        self.tree.bind("<B1-Motion>", lambda _e: self._schedule_grid(), add="+")
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
        self.add_button = ttk.Button(edit, text="Add", command=self._add_user)
        self.add_button.grid(row=0, column=2, padx=(0, 6))
        self.remove_button = ttk.Button(edit, text="Remove selected", command=self._remove_selected)
        self.remove_button.grid(row=0, column=3, padx=(0, 6))
        self.rescan_button = ttk.Button(edit, text="Full re-scan selected", command=self._rescan_selected)
        self.rescan_button.grid(row=0, column=4)

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
        est.bind("<Configure>", lambda e: [_set_wrap(lb, e.width - 24) for lb in labels])

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
        ttk.Checkbutton(tab, text="Also add the post's account to the saved list (From user tab)",
                        variable=self.add_owner).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        hint = ttk.Label(tab, foreground="gray", justify="left", text=(
            "Paste a link to a post or reel, e.g. https://www.instagram.com/p/… "
            "It's saved in the output folder under the account's name, so a From user "
            "download of that account skips it. Public accounts only."))
        hint.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        tab.bind("<Configure>", lambda e: _set_wrap(hint, e.width - 24))

    def _build_files_tab(self, tab: ttk.Frame) -> None:
        """Usernames and post links read from a .txt file, in two lists."""
        tab.columnconfigure(0, weight=1, uniform="files")
        tab.columnconfigure(1, weight=1, uniform="files")
        tab.rowconfigure(1, weight=1)
        picker = ttk.Frame(tab)
        picker.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        picker.columnconfigure(1, weight=1)
        ttk.Label(picker, text="Input file:").grid(row=0, column=0, padx=(0, 6))
        entry = ttk.Entry(picker, textvariable=self.files_path)
        entry.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        entry.bind("<Return>", lambda _e: self._load_files())
        ttk.Button(picker, text="Browse…", command=self._browse_files).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(picker, text="Load", command=self._load_files).grid(row=0, column=3)

        self.files_users_box = ttk.LabelFrame(tab, text="Usernames", padding=4)
        self.files_users_box.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        self.files_users_tree = self._files_tree(self.files_users_box, "Username")
        self.files_links_box = ttk.LabelFrame(tab, text="Direct links", padding=4)
        self.files_links_box.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        self.files_links_tree = self._files_tree(self.files_links_box, "Post link")

        users_buttons = ttk.Frame(tab)
        users_buttons.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.files_add_all_button = ttk.Button(users_buttons, text="Add all usernames",
                                               command=lambda: self._add_files_users(False))
        self.files_add_all_button.grid(row=0, column=0, padx=(0, 6))
        self.files_add_sel_button = ttk.Button(users_buttons, text="Add selected",
                                               command=lambda: self._add_files_users(True))
        self.files_add_sel_button.grid(row=0, column=1)
        links_buttons = ttk.Frame(tab)
        links_buttons.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(6, 0))
        self.files_dl_all_button = ttk.Button(links_buttons, text="Download all links",
                                              command=lambda: self._start_files_links(False))
        self.files_dl_all_button.grid(row=0, column=0, padx=(0, 6))
        self.files_dl_sel_button = ttk.Button(links_buttons, text="Download selected",
                                              command=lambda: self._start_files_links(True))
        self.files_dl_sel_button.grid(row=0, column=1)
        ttk.Checkbutton(tab, text="Also add each link's account to the saved list (From user tab)",
                        variable=self.files_add_owner).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        hint = ttk.Label(tab, foreground="gray", justify="left", text=(
            "A .txt file, one username or one https://www.instagram.com/p/… link per line. "
            "No comments, CSV or JSON: other lines are skipped and listed in the log. "
            "Usernames are only added to the saved list; links are downloaded now. Public accounts only."))
        hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tab.bind("<Configure>", lambda e: _set_wrap(hint, e.width - 24))

    def _files_tree(self, box: ttk.LabelFrame, heading: str) -> ttk.Treeview:
        """One of the From file tab's lists: a single column, several rows selectable."""
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        tree = ttk.Treeview(box, columns=("value",), show="headings", selectmode="extended", height=8)
        tree.heading("value", text=heading, anchor="w")
        tree.column("value", anchor="w", stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        return tree

    # -------------------------------------------------------------- files tab

    def _browse_files(self) -> None:
        """Pick a .txt file and load it at once."""
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Usernames and post links",
            filetypes=[("Text files", "*.txt")], initialdir=str(paths.APP_DIR))
        if chosen:
            self.files_path.set(chosen)
            self._load_files()

    def _load_files(self) -> None:
        """Read the chosen file (replacing both lists). A refused file changes nothing."""
        path = self.files_path.get().strip()
        if not path:
            return
        try:
            text = read_entries_file(path)
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e), parent=self.root)
            return
        self.files_users, self.files_links, rejected = parse_entries(text)
        self._show_files_lists()
        summary = (f"Loaded {Path(path).name}: {len(self.files_users)} username(s), "
                   f"{len(self.files_links)} link(s).")
        self._append_log(summary)
        if rejected:
            self._append_log(f"Skipped {len(rejected)} line(s) that are not a username or an "
                             "https://www.instagram.com post link:")
            for line in rejected[:REJECTED_SHOWN]:
                self._append_log(f"  {line}")
            if len(rejected) > REJECTED_SHOWN:
                self._append_log(f"  … and {len(rejected) - REJECTED_SHOWN} more")
        self.status.set(summary)

    def _show_files_lists(self) -> None:
        """Redraw both lists from files_users / files_links, keeping the selection.
        Row ids are the username and the shortcode; the text is what's shown."""
        listed = set(self.store.usernames())
        for tree, rows in (
            (self.files_users_tree, [(n, n + (ALREADY_LISTED if n in listed else "")) for n in self.files_users]),
            (self.files_links_tree, [(code, url) for code, url in self.files_links]),
        ):
            selected = set(tree.selection())
            tree.delete(*tree.get_children())
            for iid, text in rows:
                tree.insert("", "end", iid=iid, values=(text,))
            tree.selection_set([iid for iid, _t in rows if iid in selected])
        self.files_users_box.configure(text=f"Usernames ({len(self.files_users)})")
        self.files_links_box.configure(text=f"Direct links ({len(self.files_links)})")

    def _add_files_users(self, only_selected: bool) -> None:
        """Add all (or the selected) usernames from the file to the saved list."""
        if not self.files_users:
            messagebox.showinfo(TITLE, NO_FILE_USERS, parent=self.root)
            return
        if only_selected:
            chosen = set(self.files_users_tree.selection())
            if not chosen:
                messagebox.showinfo(TITLE, SELECT_FIRST, parent=self.root)
                return
            names = [n for n in self.files_users if n in chosen]
        else:
            names = list(self.files_users)
        added = 0
        try:
            for name in names:
                added += self.store.add_user(name)
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
        except ValueError as e:  # parse_entries already checked it; just in case
            messagebox.showwarning(TITLE, str(e), parent=self.root)
            return
        self._refresh_table()
        self._show_files_lists()
        text = f"Added {added} of {len(names)} username(s); {len(names) - added} already in the list."
        self._append_log(text)
        self.status.set(text)

    def _start_files_links(self, only_selected: bool) -> None:
        """Download all (or the selected) links from the file on the worker thread."""
        if self.worker and self.worker.is_alive():
            return  # already running
        if not self.files_links:
            messagebox.showinfo(TITLE, NO_FILE_LINKS, parent=self.root)
            return
        if only_selected:
            chosen = set(self.files_links_tree.selection())
            if not chosen:
                messagebox.showinfo(TITLE, SELECT_LINKS_FIRST, parent=self.root)
                return
            codes = [c for c, _url in self.files_links if c in chosen]
        else:
            codes = [c for c, _url in self.files_links]
        self._save_settings()
        if not self._media_chosen() or not self._store_writable():
            return
        # Plain values for the worker: it must not read tkinter variables.
        self._launch(self._run_links, codes, self.files_add_owner.get(), self.store.settings)

    # -------------------------------------------------------------- user list

    def _refresh_table(self) -> None:
        """Redraw the user table from the store, keeping the selection."""
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        column, descending = self.sort or (None, False)
        for row, user in enumerate(sort_users(self.store.users, column, descending)):
            name, st = user["username"], user["stats"]
            ran = bool(user.get("last_run"))
            # Every other row is light blue; counted in display order, so sorting keeps the stripes.
            self.tree.insert("", "end", iid=name, tags=(STRIPE_TAG,) if row % 2 else (), values=(
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
        """Make every column as wide as its longest text (heading included) plus
        CELL_PADDING, and the window wide enough for the table.

        Widths are measured in the fonts the table really uses, so nothing is cut
        off on high-DPI screens where text is larger than a fixed pixel width.
        """
        cell_font = tkfont.nametofont("TkDefaultFont")
        heading_font = tkfont.nametofont("TkHeadingFont")
        rows = [self.tree.item(iid)["values"] for iid in self.tree.get_children()]
        total = 0
        for i, (key, heading) in enumerate(COLUMNS.items()):
            texts = [str(row[i]) for row in rows if i < len(row)]
            # Room for the sort arrow, so sorting doesn't change the column widths.
            width = max([heading_font.measure(heading + SORT_DOWN)]
                        + [cell_font.measure(t) for t in texts])
            width += CELL_PADDING
            self.tree.column(key, width=width, minwidth=width)
            total += width
        # Table + scrollbar + the frame and grid padding around it.
        # Table + scrollbar + the frame and grid padding around it, and the preview.
        extra = self.preview_frame.winfo_reqwidth() + 16 if self.show_preview.get() else 0
        self.root.minsize(total + 80 + extra, MIN_HEIGHT)
        self._schedule_grid()

    def _schedule_grid(self) -> None:
        """Redraw the cell borders once Tk is idle (many changes in a row draw once)."""
        if not self._grid_pending:
            self._grid_pending = True
            self.tree.after_idle(self._draw_grid)

    def _draw_grid(self) -> None:
        """Place thin lines over the table along every row and column edge."""
        self._grid_pending = False
        if not self.tree.winfo_exists():
            return
        widths = [int(self.tree.column(key, "width")) for key in COLUMNS]
        rows = [box for box in (self.tree.bbox(iid) for iid in self.tree.get_children()) if box]
        lines = grid_lines(widths, rows)
        while len(self.grid_frames) < len(lines):
            line = tk.Frame(self.tree, background=GRID_COLOR, borderwidth=0, highlightthickness=0)
            # A click on a line still selects the row underneath.
            line.bind("<Button-1>", self._click_through)
            self.grid_frames.append(line)
        for line, (x, y, w, h) in zip(self.grid_frames, lines):
            line.place(x=x, y=y, width=w, height=h)
        for line in self.grid_frames[len(lines):]:
            line.place_forget()

    def _click_through(self, event) -> None:
        """Select the row under a grid line, as a click on the table would."""
        y = event.widget.winfo_y() + event.y
        row = self.tree.identify_row(y)
        if row:
            self.tree.selection_set(row)
            self.tree.focus(row)

    def _sort_by(self, column: str) -> None:
        """A heading was clicked: sort by that column, or reverse it if it already is."""
        if self.sort and self.sort[0] == column:
            self.sort = (column, not self.sort[1])
        else:
            self.sort = (column, False)
        for key, heading in COLUMNS.items():
            arrow = (SORT_DOWN if self.sort[1] else SORT_UP) if key == column else ""
            self.tree.heading(key, text=heading + arrow)
        self._refresh_table()

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
            text = format_duration(time.monotonic() - started)
            self.tree.set(name, "time", text)
            # The ticking time can outgrow the column (e.g. "59 s" -> "1 min 0 s").
            needed = tkfont.nametofont("TkDefaultFont").measure(text) + CELL_PADDING
            if needed > int(self.tree.column("time", "width")):
                self._fit_columns()

    def _add_user(self) -> None:
        """Add the name in the entry box (the store validates it)."""
        text = self.new_user.get()
        if not text.strip():
            return
        try:
            added = self.store.add_user(text)
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
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
        try:
            for name in names:
                self.store.remove_user(name)
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
        self._refresh_table()
        self.status.set(f"Removed {len(names)} user(s).")

    def _rescan_selected(self) -> None:
        """Make the next "all posts" download of the selected users look at every
        post again, instead of stopping at posts already on disk (fills gaps)."""
        names = self._selected_names()
        if not names:
            return
        try:
            changed = self.store.request_full_scan(names)
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
        self._refresh_table()
        self.status.set(f"The next \"all posts\" download of {changed} user(s) looks at every post again.")

    # --------------------------------------------------------------- settings

    def _refresh_states(self) -> None:
        """Grey out "Newest N posts per user" while "Download all posts" is ticked."""
        state = "disabled" if self.all_posts.get() else "normal"
        for widget in (self.newest_label, self.limit_box, self.posts_label):
            widget.configure(state=state)

    def _form_settings(self) -> dict:
        """The settings as the form shows them (half-typed values fall back to saved ones)."""
        s = self.store.settings
        s.update(all_posts=self.all_posts.get(), images=self.images.get(), videos=self.videos.get())
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
        values = {"all_posts": self.all_posts.get(), "images": self.images.get(),
                  "videos": self.videos.get(),
                  "caption": self.caption.get(), "tags": self.tags.get(),
                  "metadata": self.metadata.get()}
        limit = self._read_limit()
        if limit is not None:  # half-typed number: keep the saved value
            values["limit"] = limit
        if self.output_dir.get().strip():
            values["output_dir"] = self.output_dir.get().strip()
        try:
            self.store.update_settings(**values)
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
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
        if not self._media_chosen():
            return
        if not self._store_writable():
            return
        self._launch(self._run, only)

    def _start_post(self) -> None:
        """Download the post in the From link tab's link box on the worker thread."""
        if self.worker and self.worker.is_alive():
            return  # already running
        try:
            shortcode = parse_post_url(self.post_link.get())
        except ValueError as e:
            messagebox.showwarning(TITLE, str(e), parent=self.root)
            return
        self._save_settings()
        if not self._media_chosen() or not self._store_writable():
            return
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
        idle = "disabled" if self.store_blocked else "normal"
        for button in (self.all_button, self.sel_button, self.post_button,
                       self.files_dl_all_button, self.files_dl_sel_button):
            button.configure(state="disabled" if running else idle)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _media_chosen(self) -> bool:
        """False (with a hint) if both Images and Videos are off: nothing to download."""
        if self.images.get() or self.videos.get():
            return True
        messagebox.showwarning(TITLE, NOTHING_CHOSEN, parent=self.root)
        return False

    def _store_writable(self) -> bool:
        """Re-read the data file. False (and the window locked) if a newer InstaKeep wrote it."""
        try:
            self.store.check_writable()
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return False
        return True

    def _block_for_newer_store(self, text: str) -> None:
        """A newer InstaKeep wrote the data file: turn off everything that saves.

        Shown once; the list stays visible. Restarting runs the new version.
        """
        first_time = not self.store_blocked
        self.store_blocked = True
        for button in (self.all_button, self.sel_button, self.post_button,
                       self.files_dl_all_button, self.files_dl_sel_button,
                       self.files_add_all_button, self.files_add_sel_button,
                       self.add_button, self.remove_button, self.rescan_button):
            button.configure(state="disabled")
        self.status.set("Read-only: a newer InstaKeep updated the data file. Restart InstaKeep.")
        if first_time:
            messagebox.showwarning(TITLE, text, parent=self.root)

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
            # No sleep while downloading, even with the screen locked. Entered on
            # this (the worker) thread, which Windows ties the request to.
            with awake.keep_awake(log=lambda text: put(("log", text))):
                results = runner.run_all(
                    self.store,
                    log=lambda text: put(("log", text)),
                    should_stop=self.stop_requested.is_set,
                    on_pause=lambda secs: put(("pause", secs)),
                    on_user_done=lambda r: put(("user_done", r)),
                    on_user_start=lambda name: put(("user_start", name)),
                    on_saved=self._on_saved,
                    only=only,
                )
            ok = sum(r.ok for r in results)
            new = sum(r.new_files for r in results)
            put(("done", f"Done. {ok}/{len(results)} user(s) OK, {new} new file(s).", True))
        except NewerStoreError as e:
            put(("done", str(e), False))  # the reload on "done" locks the window
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
                Path(settings["output_dir"]), videos=settings["videos"], images=settings["images"],
                caption=settings["caption"],
                metadata=settings["metadata"], quiet=True,
                on_pause=lambda secs: put(("pause", secs)), should_stop=self.stop_requested.is_set,
            )
            loader.context.error = lambda msg, repeat_at_end=True: log(f"warning: {msg}")
            with awake.keep_awake(log=log):
                result = download_post(loader, shortcode, log=log, tags=settings["tags"],
                                       folder_for=self.store.folder_of, on_saved=self._on_saved)
            put(("post_owner", result.owner, add_owner))
            if not result.saved:
                kind = "an image" if settings["videos"] else "a video"
                put(("done", f"Nothing downloaded: the post is {kind}.", True))
            else:
                put(("done", f"Done. {result.new_files} new file(s) from @{result.owner}.", True))
        except downloader.DownloadStopped:
            put(("done", "Stopped.", True))
        except Exception as e:  # noqa: BLE001 - every failure must reach the window
            known = cli.describe_error(e, "", post=shortcode)
            put(("done", known[1] if known else describe_unexpected(e), False))
        finally:
            lock.release()

    def _run_links(self, shortcodes: list[str], add_owner: bool, settings: dict,
                   build_loader=downloader.build_loader,
                   download_post=downloader.download_single_post) -> None:
        """Runs on the worker thread: download each post link in turn under one lock.

        A link that fails for a known reason (deleted, private, ...) is logged and
        the rest go on; a rate limit or Stop ends the run. Like _run(), every outcome
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
                Path(settings["output_dir"]), videos=settings["videos"], images=settings["images"],
                caption=settings["caption"],
                metadata=settings["metadata"], quiet=True,
                on_pause=lambda secs: put(("pause", secs)), should_stop=self.stop_requested.is_set,
            )
            loader.context.error = lambda msg, repeat_at_end=True: log(f"warning: {msg}")
            total = len(shortcodes)
            ok = new = 0
            stopped = False
            rate_limit = ""  # the message, if Instagram rate-limited the run
            with awake.keep_awake(log=log):
                for number, code in enumerate(shortcodes, 1):
                    if self.stop_requested.is_set():
                        stopped = True
                        break
                    log(f"Link {number}/{total}: {code}")
                    try:
                        result = download_post(loader, code, log=log, tags=settings["tags"],
                                               folder_for=self.store.folder_of, on_saved=self._on_saved)
                    except downloader.DownloadStopped:
                        stopped = True
                        break
                    except Exception as e:  # noqa: BLE001 - unknown errors are re-raised below
                        known = cli.describe_error(e, "", post=code)
                        if known is None:
                            raise
                        log(f"error: {known[1]}")
                        if known[0] == cli.EXIT_RATE_LIMIT:
                            rate_limit = known[1]
                            break
                        continue
                    put(("post_owner", result.owner, add_owner))
                    ok += 1
                    new += result.new_files
            summary = f"{ok}/{total} link(s) OK, {new} new file(s)."
            if rate_limit:
                put(("done", f"{rate_limit} Stopped: {summary}", False))
            else:
                put(("done", f"{'Stopped' if stopped else 'Done'}. {summary}", True))
        except Exception as e:  # noqa: BLE001 - every failure must reach the window
            put(("done", describe_unexpected(e), False))
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
                elif kind == "preview":
                    self._show_preview(msg[1], msg[2], msg[3])
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
                    if self.store.too_new:
                        self._block_for_newer_store(text)
                    elif not ok:
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
        except NewerStoreError as e:
            self._block_for_newer_store(str(e))
            return
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

    # ------------------------------------------------------------ image preview

    def _on_saved(self, saved) -> None:
        """Runs on the worker thread after a post saved new files: load its newest
        image for the preview. Videos are skipped (the preview stays as it was)."""
        path = preview.newest_image(saved)
        if path is None:
            return
        caption = preview.caption_for_post(saved, path)
        if not self.preview_on.is_set():
            self.unshown = (path, caption)  # shown if the preview is turned back on
            return
        image = preview.load_preview(path)
        if image is not None:
            self.messages.put(("preview", image, path, caption))

    def _load_in_background(self, path: Path, caption: str) -> None:
        """Load an image for the preview without blocking the window."""
        def work():
            image = preview.load_preview(path)
            if image is not None:
                self.messages.put(("preview", image, path, caption))
        threading.Thread(target=work, daemon=True).start()

    def _show_preview(self, image, path: Path, caption: str) -> None:
        """Show a loaded image (Tk thread)."""
        if not self.show_preview.get():
            self.unshown = (path, caption)
            return
        self.preview_image, self.preview_path = image, path
        self.preview_caption_text = caption
        self.preview_caption.configure(text=caption)
        self.open_image_button.configure(state="normal")
        self._render_preview()

    def _schedule_fit(self) -> None:
        if not self._fit_pending:
            self._fit_pending = True
            self.root.after(100, self._render_preview)

    def _render_preview(self) -> None:
        """Fit the current image into the preview area and show it."""
        from PIL import ImageTk  # imported here: needs Tk, and only once there's an image

        self._fit_pending = False
        if self.preview_image is None or not self.preview_area.winfo_exists():
            return
        width = self.preview_area.winfo_width()
        height = self.preview_area.winfo_height()
        if width < 2 or height < 2:  # not laid out yet: use its starting size
            width = height = int(self.preview_area.cget("width"))
        fitted = preview.fit(self.preview_image, width, height)
        self.preview_photo = ImageTk.PhotoImage(fitted, master=self.root)
        self.preview_label.configure(image=self.preview_photo, text="")

    def _toggle_preview(self) -> None:
        """Show preview ticked or unticked: show or hide the right column.

        The window gets an exact new size: as wide as before, plus or minus the
        panel. Letting it follow its contents instead (geometry("")) never settles,
        because the wrapping labels size themselves from the window's width.
        """
        self.root.update_idletasks()
        width, height = self.root.winfo_width(), self.root.winfo_height()
        panel = self.preview_frame.winfo_reqwidth() + 16  # its grid padding, both sides
        if self.show_preview.get():
            self.preview_on.set()
            self.preview_frame.grid()
            width += panel
            if self.unshown:
                path, caption = self.unshown
                self.unshown = None
                self._load_in_background(path, caption)
        else:
            self.preview_on.clear()
            self.preview_frame.grid_remove()
            width -= panel
        self._fit_columns()  # the minimum width, with or without the panel
        if width > 1 and height > 1:  # 1x1: not on screen yet, nothing to resize
            self.root.geometry(f"{width}x{height}")

    def _open_image(self) -> None:
        """Open the previewed image in the system's image viewer."""
        path = self.preview_path
        # Only ever an image file InstaKeep saved: never something that could run.
        if path is None or not preview.is_image(path) or not path.is_file():
            return
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - opens an image file in the default viewer
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path.resolve())],
                           check=False)

    def _open_folder(self) -> None:
        """Open a user's folder (or the output folder) in the file manager.

        From user tab: the selected user's. From link tab: the last downloaded post's account.
        """
        # resolve(): an absolute path can't be mistaken for an option by open/xdg-open.
        base = Path(self.output_dir.get().strip() or paths.DEFAULT_OUTPUT).resolve()
        if self.tabs.index("current") == 1:
            name = self.post_owner
        else:
            selected = self.tree.selection()
            name = selected[0] if selected else None
        # A renamed account keeps its old folder.
        sub = self.store.folder_of(name) if name else None
        folder = base / sub if sub and (base / sub).is_dir() else base
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
