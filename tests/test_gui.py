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


def test_table_shows_times_and_counts(app):
    assert app.tree["columns"] == tuple(gui.COLUMNS)
    user, _last, last_time, total, images, videos = app.tree.item("natgeo")["values"]
    assert (user, last_time, total, images, videos) == ("natgeo", "30 s", "30 s", 6, 0)


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
    app.tree.selection_set(["natgeo"])
    app.root.update()
    assert app.estimate_selected.get().startswith("Selected (1): about ")


def test_all_posts_estimate_mentions_unknown_post_counts(app):
    app.all_posts.set(True)
    assert "Post count not known yet for 1 user(s)" in app.estimate_all.get()


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
    _run_post(app, True, lambda loader, code, log, tags: downloader.PostResult("nasa_hubble", True, 3))
    assert "nasa_hubble" in store.usernames()
    assert app.tree.exists("nasa_hubble")
    log = app.log_box.get("1.0", "end")
    assert "Added @nasa_hubble to the saved list." in log
    assert "Done. 3 new file(s) from @nasa_hubble." in log
    assert str(app.post_button.cget("state")) == "normal"


def test_post_download_leaves_the_list_alone_when_unticked(app, store):
    from igdl import downloader
    _run_post(app, False, lambda loader, code, log, tags: downloader.PostResult("nasa_hubble", True, 1))
    assert store.usernames() == ["natgeo", "nasa"]
    assert app.post_owner == "nasa_hubble"  # Open folder goes there


def test_missing_post_shows_a_short_error(app, store, dialogs):
    from instaloader.exceptions import BadResponseException

    def gone(loader, code, log, tags):
        raise BadResponseException("Fetching Post metadata failed.")

    _run_post(app, True, gone)
    assert dialogs.texts("showerror") == [
        "post 'DXwaXSSEuX8' couldn't be loaded. It may have been deleted, or its account is private."]
    assert store.usernames() == ["natgeo", "nasa"]
