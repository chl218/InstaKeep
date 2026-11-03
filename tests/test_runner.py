import os

import pytest

from instakeep import runner
from instakeep.store import Store


class FakeLoader:
    class context:  # noqa: N801 - mimics instaloader's attribute
        error = None


class NotFound(Exception):
    pass


class Blocked(Exception):
    pass


def describe(e, username):
    if isinstance(e, NotFound):
        return 1, f"profile '{username}' does not exist."
    if isinstance(e, Blocked):
        return 4, "blocked"
    return None


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "instakeep.json", tmp_path / "downloads")
    for name in ("alpha", "beta", "gamma"):
        s.add_user(name)
    return s


def make_download(tmp_path, behaviour, calls, tag_calls=None):
    """behaviour: username -> number of files to create, or an exception to raise."""
    tag_calls = [] if tag_calls is None else tag_calls

    def download_user(loader, name, limit, log, should_stop, tags, stats=None, **_kw):
        calls.append((name, limit))
        tag_calls.append(tags)
        what = behaviour.get(name, 0)
        if isinstance(what, Exception):
            raise what
        folder = tmp_path / "downloads" / name
        folder.mkdir(parents=True, exist_ok=True)
        for i in range(what):
            (folder / f"{name}_{len(calls)}_{i}.jpg").write_bytes(b"x")
        return what
    return download_user


def run(store, tmp_path, behaviour, **kw):
    calls = []
    results = runner.run_all(
        store, log=lambda _m: None, build_loader=lambda *a, **k: FakeLoader(),
        download_user=make_download(tmp_path, behaviour, calls), describe_error=describe, **kw,
    )
    return results, calls


def test_downloads_every_user_with_limit(store, tmp_path):
    results, calls = run(store, tmp_path, {"alpha": 2, "beta": 0, "gamma": 5})
    assert calls == [("alpha", 5), ("beta", 5), ("gamma", 5)]
    assert [r.new_files for r in results] == [2, 0, 5]
    assert runner.exit_code(results) == runner.EXIT_OK
    assert store.users[2]["last_status"] == "ok, 5 new"


def test_tags_setting_passed_to_download(store, tmp_path):
    tag_calls = []
    download = make_download(tmp_path, {}, [], tag_calls)
    common = dict(log=lambda _m: None, build_loader=lambda *a, **k: FakeLoader(),
                  download_user=download, describe_error=describe, only=["alpha"])
    runner.run_all(store, **common)                 # default setting: tags on
    store.update_settings(tags=False)
    runner.run_all(store, **common)
    assert tag_calls == [True, False]


def test_rerun_counts_only_new_files(store, tmp_path):
    run(store, tmp_path, {"alpha": 2})
    results, _ = run(store, tmp_path, {"alpha": 0})
    assert results[0].new_files == 0


def test_one_failure_doesnt_stop_others(store, tmp_path):
    results, calls = run(store, tmp_path, {"alpha": NotFound(), "beta": 1})
    assert [c[0] for c in calls] == ["alpha", "beta", "gamma"]
    assert store.users[0]["last_status"] == "not found"
    assert runner.exit_code(results) == runner.EXIT_SOME_FAILED


def test_rate_limit_stops_the_run(store, tmp_path):
    results, calls = run(store, tmp_path, {"beta": Blocked()})
    assert [c[0] for c in calls] == ["alpha", "beta"]
    assert runner.exit_code(results) == runner.EXIT_RATE_LIMIT


def test_only_selected(store, tmp_path):
    _, calls = run(store, tmp_path, {}, only=["gamma"])
    assert calls == [("gamma", 5)]


def test_stop_before_next_user(store, tmp_path):
    _, calls = run(store, tmp_path, {}, should_stop=lambda: True)
    assert calls == []


def test_lock_blocks_second_run(tmp_path):
    first = runner.RunLock(tmp_path / "run.lock")
    assert first.acquire()
    assert not runner.RunLock(tmp_path / "run.lock").acquire()
    first.release()
    assert runner.RunLock(tmp_path / "run.lock").acquire()


def test_stale_lock_ignored(tmp_path):
    lock_file = tmp_path / "run.lock"
    lock_file.write_text("999999999")  # no such process
    assert runner.RunLock(lock_file).acquire()


def test_pid_alive():
    assert runner.pid_alive(os.getpid())
    assert not runner.pid_alive(999999999)


def test_all_posts_means_no_limit(store, tmp_path):
    store.update_settings(all_posts=True)
    _, calls = run(store, tmp_path, {}, only=["alpha"])
    assert calls == [("alpha", None)]


def test_each_user_is_timed_and_recorded(store, tmp_path):
    started = []

    def download_user(loader, name, limit, log, should_stop, tags, stats, **_kw):
        stats.images, stats.videos, stats.image_seconds, stats.media_count = 2, 1, 3.0, 9
        stats.posts = stats.new_posts = 2

    results = runner.run_all(store, log=lambda _m: None, build_loader=lambda *a, **k: FakeLoader(),
                             download_user=download_user, describe_error=describe,
                             on_user_start=started.append, only=["alpha"])
    assert started == ["alpha"] and results[0].seconds >= 0
    st = store.users[0]["stats"]
    assert st["runs"] == 1 and st["images"] == 2 and st["videos"] == 1
    assert st["image_seconds"] == 3 and st["media_count"] == 9 and st["last_images"] == 2


def test_all_posts_run_records_the_posts_it_saw_as_the_profile_size(store, tmp_path):
    # Without a login Instagram gives no post count (media_count stays None).
    store.update_settings(all_posts=True)

    def download_user(loader, name, limit, log, should_stop, tags, stats, **_kw):
        stats.posts, stats.complete = 7, True

    runner.run_all(store, log=lambda _m: None, build_loader=lambda *a, **k: FakeLoader(),
                   download_user=download_user, describe_error=describe, only=["alpha"])
    assert store.users[0]["stats"]["media_count"] == 7


def test_failed_user_counts_time_but_not_a_run(store, tmp_path):
    run(store, tmp_path, {"alpha": NotFound()}, only=["alpha"])
    assert store.users[0]["stats"]["runs"] == 0


# ------------------------------------------------- run order, early stop, renames

def recording_download(calls, behaviour=None, complete=False, userid=None):
    """A fake download_user that records its keyword arguments."""
    behaviour = behaviour or {}

    def download_user(loader, name, limit, log, should_stop, tags, stats, **kw):
        calls.append({"name": name, "limit": limit, **kw})
        what = behaviour.get(name)
        if isinstance(what, Exception):
            raise what
        stats.complete = complete
        stats.userid = userid
    return download_user


def run_with(store, download_user, **kw):
    return runner.run_all(store, log=kw.pop("log", lambda _m: None),
                          build_loader=lambda *a, **k: FakeLoader(),
                          download_user=download_user, describe_error=describe, **kw)


def test_full_run_starts_with_the_longest_without_a_download(store):
    store.record_result("alpha", "ok, 1 new", ok=True, when=__import__("datetime").datetime(2026, 1, 3))
    store.record_result("beta", "ok, 1 new", ok=True, when=__import__("datetime").datetime(2026, 1, 1))
    calls = []
    run_with(store, recording_download(calls))
    assert [c["name"] for c in calls] == ["gamma", "beta", "alpha"]  # never, oldest, newest


def test_a_rate_limited_user_keeps_its_place_in_line(store):
    _, calls = run(store, __import__("pathlib").Path(store.path).parent, {"alpha": Blocked()})
    assert calls == [("alpha", 5)]
    assert store.users[0]["last_ok"] is None  # the failed run doesn't count as a download
    calls = []
    run_with(store, recording_download(calls))
    assert calls[0]["name"] == "alpha"


def test_selected_run_keeps_the_list_order(store):
    store.record_result("alpha", "ok", ok=True)
    calls = []
    run_with(store, recording_download(calls), only=["gamma", "alpha"])
    assert [c["name"] for c in calls] == ["alpha", "gamma"]


def test_all_posts_stops_early_only_after_a_full_pass(store):
    store.update_settings(all_posts=True)
    calls = []
    run_with(store, recording_download(calls, complete=True), only=["alpha"])
    assert calls[-1]["stop_at_known"] is False      # first time: every post
    assert store.users[0]["full_scan_done"] is True
    run_with(store, recording_download(calls, complete=False), only=["alpha"])
    assert calls[-1]["stop_at_known"] is True       # after that: stop at posts on disk
    assert store.users[0]["full_scan_done"] is True  # an early stop doesn't undo it
    store.request_full_scan(["alpha"])
    run_with(store, recording_download(calls), only=["alpha"])
    assert calls[-1]["stop_at_known"] is False


def test_limited_runs_never_stop_early_or_count_as_a_full_pass(store):
    calls = []
    run_with(store, recording_download(calls, complete=False), only=["alpha"])
    assert calls[0]["stop_at_known"] is False and calls[0]["limit"] == 5
    assert store.users[0]["full_scan_done"] is False


def test_an_early_stop_doesnt_record_the_posts_seen_as_the_profile_size(store):
    store.update_settings(all_posts=True)

    def download_user(loader, name, limit, log, should_stop, tags, stats, **kw):
        stats.posts = 4  # stopped after 4 posts: not the profile's size
    run_with(store, download_user, only=["alpha"])
    assert store.users[0]["stats"]["media_count"] == 0


def test_userid_is_saved(store):
    run_with(store, recording_download([], userid=1234), only=["alpha"])
    assert store.users[0]["userid"] == 1234


def test_renamed_account_is_followed_and_keeps_its_folder(store):
    run_with(store, recording_download([], userid=42), only=["beta"])
    logs, looked_up = [], []

    def lookup(loader, userid):
        looked_up.append(userid)
        return "beta_new"
    run_with(store, recording_download([], {"beta": NotFound()}), only=["beta"],
             lookup_username=lookup, log=logs.append)
    assert looked_up == [42]
    assert store.usernames() == ["alpha", "beta_new", "gamma"]
    assert store.folder_of("beta_new") == "beta"
    assert any("@beta is now called @beta_new" in line for line in logs)
    calls = []
    run_with(store, recording_download(calls), only=["beta_new"])
    assert calls[0]["folder_name"] == "beta"  # history stays in one folder


def test_not_found_without_a_saved_id_is_just_not_found(store):
    def lookup(loader, userid):
        raise AssertionError("no ID to look up")
    results = run_with(store, recording_download([], {"alpha": NotFound()}), only=["alpha"],
                       lookup_username=lookup)
    assert results[0].status == "not found"


def test_rename_to_a_name_already_listed_changes_nothing(store):
    run_with(store, recording_download([], userid=42), only=["beta"])
    logs = []
    run_with(store, recording_download([], {"beta": NotFound()}), only=["beta"],
             lookup_username=lambda loader, userid: "gamma", log=logs.append)
    assert store.usernames() == ["alpha", "beta", "gamma"]
    assert any("already in the list" in line for line in logs)


def test_rate_limited_rename_check_ends_the_run(store):
    for name in ("alpha", "beta"):
        run_with(store, recording_download([], userid=7), only=[name])

    def lookup(loader, userid):
        raise Blocked()
    calls = []
    store.record_result("gamma", "ok", ok=True)  # order: alpha, beta, gamma
    run_with(store, recording_download(calls, {"alpha": NotFound()}), lookup_username=lookup)
    assert [c["name"] for c in calls] == ["alpha"]


# ------------------------------------------------------------ newer data file

def test_a_newer_data_file_stops_the_run_before_downloading(store, tmp_path):
    import json
    data = json.loads(store.path.read_text(encoding="utf-8"))
    store.path.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")
    calls = []
    with pytest.raises(runner.NewerStoreError):
        run_with(store, recording_download(calls))
    assert calls == []


def test_headless_run_exits_3_for_a_newer_data_file(store, tmp_path):
    import json
    data = json.loads(store.path.read_text(encoding="utf-8"))
    store.path.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")
    assert runner.run_headless(store) == runner.EXIT_SETUP == 3
    log = next((tmp_path / "logs").glob("run-*.log")).read_text(encoding="utf-8")
    assert "newer version of InstaKeep" in log


# ------------------------------------------------------------------ heartbeat

def test_lock_heartbeat_keeps_the_file_fresh(tmp_path):
    lock_file = tmp_path / "run.lock"
    lock = runner.RunLock(lock_file, heartbeat=0.05)
    assert lock.acquire()
    os.utime(lock_file, (1, 1))  # pretend it's ancient
    deadline = __import__("time").monotonic() + 5
    while lock_file.stat().st_mtime < 1000 and __import__("time").monotonic() < deadline:
        __import__("time").sleep(0.02)
    assert lock_file.stat().st_mtime > 1000
    assert not runner.RunLock(lock_file).acquire()  # still held
    lock.release()
    assert not lock_file.exists()


def test_lock_not_touched_for_an_hour_is_taken_over(tmp_path):
    lock_file = tmp_path / "run.lock"
    lock_file.write_text(str(os.getpid()))  # a live PID (e.g. reused after a crash)
    old = __import__("time").time() - runner.STALE_LOCK_SECONDS - 10
    os.utime(lock_file, (old, old))
    lock = runner.RunLock(lock_file)
    assert lock.acquire()
    lock.release()


def test_fresh_lock_with_a_live_pid_is_respected(tmp_path):
    lock_file = tmp_path / "run.lock"
    lock_file.write_text(str(os.getpid()))
    assert not runner.RunLock(lock_file).acquire()


def test_images_setting_passed_to_the_loader(store):
    built = []
    store.update_settings(images=False, videos=True)
    runner.run_all(store, log=lambda _m: None,
                   build_loader=lambda *a, **k: built.append(k) or FakeLoader(),
                   download_user=recording_download([]), describe_error=describe, only=["alpha"])
    assert built[0]["images"] is False and built[0]["videos"] is True


def test_nothing_to_download_when_images_and_videos_are_off(store):
    store.update_settings(images=False, videos=False)
    calls, logs = [], []
    results = run_with(store, recording_download(calls), log=logs.append)
    assert results == [] and calls == []
    assert any("Images and Videos are both off" in line for line in logs)
