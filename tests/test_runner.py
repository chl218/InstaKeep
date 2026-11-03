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

    def download_user(loader, name, limit, log, should_stop, tags, stats=None):
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

    def download_user(loader, name, limit, log, should_stop, tags, stats):
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

    def download_user(loader, name, limit, log, should_stop, tags, stats):
        stats.posts = 7

    runner.run_all(store, log=lambda _m: None, build_loader=lambda *a, **k: FakeLoader(),
                   download_user=download_user, describe_error=describe, only=["alpha"])
    assert store.users[0]["stats"]["media_count"] == 7


def test_failed_user_counts_time_but_not_a_run(store, tmp_path):
    run(store, tmp_path, {"alpha": NotFound()}, only=["alpha"])
    assert store.users[0]["stats"]["runs"] == 0
