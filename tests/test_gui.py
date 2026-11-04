"""The window, tested headless: conftest.py keeps it hidden and fakes the dialogs."""

import time
import tkinter as tk
from tkinter import font as tkfont

import pytest

from instakeep import gui, runner
from instakeep.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "instakeep.json", tmp_path / "downloads")
    s.add_user("natgeo")
    s.add_user("nasa")
    s.record_result("natgeo", "ok, 4 new", run_stats={
        "runs": 1, "seconds": 30, "posts": 8, "new_posts": 4, "images": 6, "image_seconds": 12,
        "queries": 3, "media_count": 120, "last_seconds": 30, "last_images": 6})
    return s


@pytest.fixture(scope="session")
def tk_root():
    # One Tk interpreter for the whole session: on Windows, creating and destroying
    # many tk.Tk() roots in one process can fail with "Can't find a usable tk.tcl".
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available for tkinter")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, store):
    window = tk.Toplevel(tk_root)  # each test gets a fresh, hidden window
    window.withdraw()
    app = gui.App(window, store)
    window.update()
    yield app
    window.destroy()


def select(app, names):
    """Select rows and run what the table's <<TreeviewSelect>> binding runs.

    Tk doesn't deliver that event to a window that was never shown on every
    platform (it's dropped on macOS with Python 3.14, even with event_generate),
    so call the handler directly. test_selecting_rows_refreshes_the_estimate
    checks that the binding is there.
    """
    app.tree.selection_set(names)
    app._refresh_estimate()


def test_selecting_rows_refreshes_the_estimate(app):
    assert app.tree.bind("<<TreeviewSelect>>")  # the click -> estimate wiring


def test_table_shows_times_and_counts(app):
    assert app.tree["columns"] == tuple(gui.COLUMNS)
    row = dict(zip(gui.COLUMNS, app.tree.item("natgeo")["values"]))
    assert row["user"] == "natgeo" and row["result"] == "ok" and row["count"] == 6
    assert (row["time"], row["longest"], row["total"]) == ("30 s", "30 s", "30 s")
    assert (row["images"], row["videos"]) == (6, 0)
    never = dict(zip(gui.COLUMNS, app.tree.item("nasa")["values"]))
    assert never["last"] == "never" and never["result"] == never["count"] == ""


def test_columns_fit_their_text(app):
    cell_font = tkfont.nametofont("TkDefaultFont")
    for iid in app.tree.get_children():
        for key, value in zip(gui.COLUMNS, app.tree.item(iid)["values"]):
            assert cell_font.measure(str(value)) < app.tree.column(key, "width")


def test_download_all_posts_greys_out_newest(app, store):
    app.all_posts.set(True)
    app._refresh_states()
    assert str(app.limit_box.cget("state")) == "disabled"
    assert store.settings["all_posts"] is True  # saved right away
    app.all_posts.set(False)
    app._refresh_states()
    assert str(app.limit_box.cget("state")) == "normal"


def test_estimate_for_all_and_selected(app):
    assert app.estimate_all.get().startswith("All 2 user(s): about ")
    assert "rate-limit pauses" in app.estimate_all.get()
    assert app.estimate_selected.get().startswith("Select users")
    select(app, ["natgeo"])
    assert app.estimate_selected.get().startswith("Selected (1): about ")


def test_estimate_leaves_out_users_never_downloaded(app):
    assert "Not counted: 1 user(s) never downloaded" in app.estimate_all.get()
    select(app, ["nasa"])
    assert "none of them has been downloaded before" in app.estimate_selected.get()


def test_live_timer_counts_up(app):
    app.timing = ("nasa", time.monotonic() - 75)
    app._tick_timer()
    assert app.tree.set("nasa", "time") == "1 min 15 s"


def test_button_error_goes_to_log_with_traceback(app, dialogs, capsys):
    try:
        raise ValueError("bad button")
    except ValueError as e:
        app._on_callback_error(ValueError, e, e.__traceback__)
    assert dialogs.texts("showerror") == ["unexpected error (ValueError): bad button\n\n"
                                          "The log has the details."]
    assert "Traceback (most recent call last)" in app.log_box.get("1.0", "end")
    assert "ValueError: bad button" in capsys.readouterr().err  # Tk's console traceback


def test_lock_failure_ends_the_run_and_reenables_buttons(app, dialogs, monkeypatch):
    def broken(self):
        raise PermissionError("lock folder is read-only")

    monkeypatch.setattr(runner.RunLock, "acquire", broken)
    app._start(None)
    app.worker.join(timeout=5)
    app._poll_messages()
    assert str(app.all_button.cget("state")) == "normal"
    assert dialogs.texts("showerror")[0].startswith("unexpected error (PermissionError)")


def test_remove_asks_first_and_keeps_files(app, store, dialogs):
    app.tree.selection_set(["nasa"])
    app._remove_selected()
    assert "Downloaded files are kept." in dialogs.texts("askyesno")[0]
    assert store.usernames() == ["natgeo"]


def test_download_selected_without_selection_shows_hint(app, dialogs):
    app.tree.selection_set([])
    app._start_selected()
    assert dialogs.texts("showinfo") == [gui.SELECT_FIRST]


def test_tabs_are_batch_and_individual(app):
    assert [app.tabs.tab(t, "text") for t in app.tabs.tabs()] == ["Batch", "Individual"]


def test_bad_post_link_shows_a_warning(app, dialogs):
    app.post_link.set("https://www.instagram.com/natgeo/")
    app._start_post()
    assert dialogs.texts("showwarning")[0].startswith("Not an Instagram post link")
    assert app.worker is None


def _run_post(app, add_owner, download_post):
    from types import SimpleNamespace

    def build_loader(*_a, **_kw):
        return SimpleNamespace(context=SimpleNamespace())

    app._run_post("DXwaXSSEuX8", add_owner, app.store.settings,
                  build_loader=build_loader, download_post=download_post)
    app._poll_messages()


def test_post_download_can_add_its_account(app, store):
    from igdl import downloader
    _run_post(app, True, lambda loader, code, log, tags, **kw: downloader.PostResult("nasa_hubble", True, 3))
    assert "nasa_hubble" in store.usernames()
    assert app.tree.exists("nasa_hubble")
    log = app.log_box.get("1.0", "end")
    assert "Added @nasa_hubble to the saved list." in log
    assert "Done. 3 new file(s) from @nasa_hubble." in log
    assert str(app.post_button.cget("state")) == "normal"


def test_post_download_leaves_the_list_alone_when_unticked(app, store):
    from igdl import downloader
    _run_post(app, False, lambda loader, code, log, tags, **kw: downloader.PostResult("nasa_hubble", True, 1))
    assert store.usernames() == ["natgeo", "nasa"]
    assert app.post_owner == "nasa_hubble"  # Open folder goes there


def test_missing_post_shows_a_short_error(app, store, dialogs):
    from instaloader.exceptions import BadResponseException

    def gone(loader, code, log, tags, **kw):
        raise BadResponseException("Fetching Post metadata failed.")

    _run_post(app, True, gone)
    assert dialogs.texts("showerror") == [
        "post 'DXwaXSSEuX8' couldn't be loaded. It may have been deleted, or its account is private."]
    assert store.usernames() == ["natgeo", "nasa"]


def _make_file_newer(store):
    import json
    data = json.loads(store.path.read_text(encoding="utf-8"))
    store.path.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")


def test_newer_data_file_locks_the_window_instead_of_downloading(app, store, dialogs):
    _make_file_newer(store)  # e.g. a newer --run after a git pull
    app._start(None)
    assert app.worker is None  # nothing downloaded that couldn't be recorded
    assert app.store_blocked
    assert "newer version of InstaKeep" in dialogs.texts("showwarning")[0]
    for button in (app.all_button, app.sel_button, app.post_button, app.add_button):
        assert str(button.cget("state")) == "disabled"
    app._set_running(False)  # e.g. after a run: stays locked
    assert str(app.all_button.cget("state")) == "disabled"
    assert app.tree.exists("natgeo")  # the list is still shown


def test_newer_data_file_found_on_a_settings_change(app, store, dialogs):
    _make_file_newer(store)
    app.videos.set(True)  # saving the option fails: the window locks, no traceback dialog
    assert app.store_blocked and dialogs.texts("showerror") == []
    assert len(dialogs.texts("showwarning")) == 1
    app.caption.set(True)
    assert len(dialogs.texts("showwarning")) == 1  # told once


def test_window_opened_on_a_newer_file_starts_locked(tk_root, store, dialogs):
    _make_file_newer(store)
    window = tk.Toplevel(tk_root)
    window.withdraw()
    try:
        app = gui.App(window, Store(store.path, store.default_output))
        assert app.store_blocked
        assert str(app.all_button.cget("state")) == "disabled"
    finally:
        window.destroy()


def test_full_rescan_selected(app, store):
    store.record_result("natgeo", "ok", ok=True, full_scan=True)
    app.store.reload()
    app.tree.selection_set(["natgeo"])
    app._rescan_selected()
    assert store.users[0]["full_scan_done"] is False
    assert "looks at every post again" in app.status.get()


def test_post_download_uses_a_renamed_accounts_folder(app, store):
    from igdl import downloader
    store.rename_user("natgeo", "natgeo_new")
    seen = []

    def download_post(loader, code, log, tags, folder_for, **_kw):
        seen.append(folder_for("natgeo_new"))
        return downloader.PostResult("natgeo_new", True, 1)
    _run_post(app, False, download_post)
    assert seen == ["natgeo"]


def test_cells_are_right_aligned_and_headings_centered(app):
    for key in gui.COLUMNS:
        assert str(app.tree.column(key, "anchor")) == "e"
        assert str(app.tree.heading(key, "anchor")) == "center"


def test_columns_are_as_wide_as_their_longest_text(app):
    cell_font = tkfont.nametofont("TkDefaultFont")
    heading_font = tkfont.nametofont("TkHeadingFont")
    rows = [app.tree.item(iid)["values"] for iid in app.tree.get_children()]
    for i, (key, heading) in enumerate(gui.COLUMNS.items()):
        longest = max([heading_font.measure(heading + gui.SORT_DOWN)]
                      + [cell_font.measure(str(row[i])) for row in rows])
        assert app.tree.column(key, "width") == longest + gui.CELL_PADDING
        assert not app.tree.column(key, "stretch")


def test_ticking_time_widens_its_column(app):
    before = app.tree.column("time", "width")
    app.timing = ("natgeo", time.monotonic() - 100 * 3600 - 59 * 60)  # "100 h 59 min"
    app._tick_timer()
    needed = tkfont.nametofont("TkDefaultFont").measure("100 h 59 min") + gui.CELL_PADDING
    assert app.tree.column("time", "width") >= needed > before


def test_clicking_a_heading_sorts_and_clicking_again_reverses(app):
    assert app.tree.get_children() == ("natgeo", "nasa")  # the saved list order
    assert app.tree.heading("images", "command")  # every heading is clickable
    app._sort_by("images")
    assert app.tree.get_children() == ("nasa", "natgeo")  # 0 images, then 6
    assert app.tree.heading("images", "text") == "Images" + gui.SORT_UP
    app._sort_by("images")
    assert app.tree.get_children() == ("natgeo", "nasa")
    assert app.tree.heading("images", "text") == "Images" + gui.SORT_DOWN
    app._sort_by("user")
    assert app.tree.get_children() == ("nasa", "natgeo")
    assert app.tree.heading("images", "text") == "Images"  # only one arrow


def test_sort_stays_after_the_table_is_redrawn(app, store):
    app._sort_by("user")
    store.add_user("aaa")
    app._refresh_table()
    assert app.tree.get_children() == ("aaa", "nasa", "natgeo")


def test_sorting_uses_values_not_the_shown_text():
    from instakeep.store import empty_stats

    def user(name, seconds, ran=True):
        stats = {**empty_stats(), "last_seconds": seconds}
        return {"username": name, "last_run": "2026-01-01T00:00:00" if ran else None, "stats": stats}

    users = [user("slow", 75), user("fast", 45), user("never", 0, ran=False)]
    # "1 min 15 s" < "45 s" as text, but 75 > 45 seconds.
    assert [u["username"] for u in gui.sort_users(users, "time")] == ["never", "fast", "slow"]
    assert [u["username"] for u in gui.sort_users(users, None)] == ["slow", "fast", "never"]


def test_grid_lines_border_every_cell():
    # Two columns (50 and 30 px wide), two rows 20 px high starting below a 25 px heading.
    rows = [(1, 25, 80, 20), (1, 45, 80, 20)]
    lines = gui.grid_lines([50, 30], rows)
    assert (1, 44, 80, 1) in lines and (1, 64, 80, 1) in lines  # under each row
    assert (50, 25, 1, 40) in lines and (80, 25, 1, 40) in lines  # column edges, below the heading
    assert len(lines) == 4
    assert gui.grid_lines([50, 30], []) == []  # empty table: no lines


def test_drawing_the_grid_places_a_line_per_border(app, monkeypatch):
    # A hidden window has no row positions (bbox is empty), so give it some.
    boxes = {"natgeo": (1, 25, 300, 20), "nasa": (1, 45, 300, 20)}
    monkeypatch.setattr(app.tree, "bbox", lambda iid, column=None: boxes.get(iid, ""))
    app._draw_grid()
    widths = [int(app.tree.column(k, "width")) for k in gui.COLUMNS]
    expected = gui.grid_lines(widths, [boxes[i] for i in app.tree.get_children()])
    placed = [f for f in app.grid_frames if f.winfo_manager() == "place"]
    assert [(int(f.place_info()["x"]), int(f.place_info()["y"]),
             int(f.place_info()["width"]), int(f.place_info()["height"])) for f in placed] == expected
    boxes.pop("nasa")  # one row scrolled out of view: its lines are hidden, not left behind
    app._draw_grid()
    assert len([f for f in app.grid_frames if f.winfo_manager() == "place"]) == len(gui.COLUMNS) + 1


def test_images_checkbox_is_on_by_default_and_saved(app, store):
    assert app.images.get() is True
    app.images.set(False)
    assert store.settings["images"] is False


def test_nothing_chosen_warns_instead_of_downloading(app, dialogs):
    app.images.set(False)
    app.videos.set(False)
    app._start(None)
    assert app.worker is None
    assert dialogs.texts("showwarning") == [gui.NOTHING_CHOSEN]


def test_window_download_keeps_the_computer_awake_while_it_runs(app, monkeypatch):
    from instakeep import awake

    events = []

    class Recorder:
        def __init__(self, log=None):
            events.append("awake")

        def __enter__(self):
            return True

        def __exit__(self, *exc):
            events.append("sleep allowed")

    monkeypatch.setattr(awake, "keep_awake", Recorder)
    monkeypatch.setattr(runner, "run_all", lambda *a, **k: events.append("download") or [])
    app._run(None)  # what the worker thread runs
    assert events == ["awake", "download", "sleep allowed"]


# ------------------------------------------------------------- image preview

def _jpeg(path):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 300), (10, 120, 200)).save(path, "JPEG")
    return path


def _drain(app):
    """Wait for background preview loading, then handle its messages."""
    deadline = time.monotonic() + 5
    while app.messages.empty() and time.monotonic() < deadline:
        time.sleep(0.02)
    app._poll_messages()


def test_preview_is_on_at_start_and_beside_the_tabs(app):
    assert app.show_preview.get() is True
    assert app.preview_frame.winfo_manager() == "grid"
    assert app.preview_frame.master is app.tabs.master  # same row as the tabs (layout B)
    assert app.preview_label.cget("text") == gui.NO_IMAGE


def test_saved_image_is_previewed_and_videos_are_skipped(app, tmp_path):
    from datetime import datetime

    from igdl.downloader import SavedPost
    img = _jpeg(tmp_path / "downloads" / "natgeo" / "natgeo_x_1.jpg")
    app._on_saved(SavedPost("natgeo", "DfN9", datetime(2026, 11, 1), [img]))  # as the worker does
    app._poll_messages()
    assert app.preview_path == img and app.preview_photo is not None
    assert app.preview_label.cget("text") == ""  # the image replaced "No image yet"
    assert "@natgeo · 2026-11-01 · DfN9" in app.preview_caption.cget("text")
    assert str(app.open_image_button.cget("state")) == "normal"
    video = tmp_path / "downloads" / "natgeo" / "v.mp4"
    app._on_saved(SavedPost("natgeo", "V1", datetime(2026, 11, 2), [video]))
    app._poll_messages()
    assert app.preview_path == img  # unchanged


def test_hiding_the_preview_stops_loading_and_shows_the_newest_when_back(app, tmp_path):
    from datetime import datetime

    from igdl.downloader import SavedPost
    app.show_preview.set(False)
    app._toggle_preview()
    assert app.preview_frame.winfo_manager() == ""  # hidden
    img = _jpeg(tmp_path / "downloads" / "nasa" / "nasa_y.jpg")
    app._on_saved(SavedPost("nasa", "Y1", datetime(2026, 11, 3), [img]))
    assert app.messages.empty()  # nothing loaded while hidden
    app.show_preview.set(True)
    app._toggle_preview()
    _drain(app)
    assert app.preview_frame.winfo_manager() == "grid" and app.preview_path == img


def test_images_from_before_the_session_are_not_shown(tk_root, store, tmp_path):
    _jpeg(tmp_path / "downloads" / "natgeo" / "natgeo_2026-11-01_23-53-04_AbC.jpg")
    window = tk.Toplevel(tk_root)
    window.withdraw()
    try:
        app = gui.App(window, store)
        window.update()
        time.sleep(0.2)  # nothing may be loading in the background either
        app._poll_messages()
        assert app.preview_path is None and app.preview_label.cget("text") == gui.NO_IMAGE
        app.show_preview.set(False)
        app._toggle_preview()
        app.show_preview.set(True)
        app._toggle_preview()  # turning it back on doesn't look on disk either
        time.sleep(0.2)
        app._poll_messages()
        assert app.preview_path is None
    finally:
        window.destroy()


def test_preview_setting_is_not_saved(app, store):
    app.show_preview.set(False)
    app._toggle_preview()
    assert "show_preview" not in store.settings and "preview" not in store.settings


def test_every_other_row_is_light_blue_even_after_sorting(app, store):
    store.add_user("aaa")
    app._refresh_table()

    def striped():
        return [gui.STRIPE_TAG in app.tree.item(iid, "tags") for iid in app.tree.get_children()]

    assert striped() == [False, True, False]
    assert str(app.tree.tag_configure(gui.STRIPE_TAG, "background")) == gui.STRIPE_COLOR
    app._sort_by("user")  # new order, same stripes
    assert app.tree.get_children() == ("aaa", "nasa", "natgeo") and striped() == [False, True, False]


def test_hiding_the_preview_gives_the_window_a_fixed_size(app, monkeypatch):
    # geometry("") made the window follow its contents, and the wrapping labels
    # (sized from the window) kept resizing it forever. Now it gets an exact size.
    sizes = []
    monkeypatch.setattr(app.root, "winfo_width", lambda: 1500)
    monkeypatch.setattr(app.root, "winfo_height", lambda: 800)
    monkeypatch.setattr(app.root, "geometry", lambda size=None: sizes.append(size))
    panel = app.preview_frame.winfo_reqwidth() + 16
    app.show_preview.set(False)
    app._toggle_preview()
    app.show_preview.set(True)
    app._toggle_preview()
    assert sizes == [f"{1500 - panel}x800", f"{1500 + panel}x800"]
    assert "" not in sizes


def test_wrapping_only_changes_when_the_width_does(app, monkeypatch):
    label = gui.ttk.Label(app.root, text="some long text")
    gui._set_wrap(label, 400)
    assert int(str(label.cget("wraplength"))) == 376 + 24
    calls = []
    real = label.configure
    monkeypatch.setattr(label, "configure", lambda **kw: calls.append(kw) or real(**kw))
    gui._set_wrap(label, 400)  # same width: left alone, so no new layout pass
    assert calls == []
    gui._set_wrap(label, 50)   # never narrower than 200
    assert calls == [{"wraplength": 200}]
