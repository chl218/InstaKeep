import json

import pytest

from igdl.security import normalize_username
from instakeep.store import DEFAULT_LIMIT, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data" / "instakeep.json", tmp_path / "downloads")


def test_defaults_when_missing(store, tmp_path):
    assert store.users == []
    assert store.settings["limit"] == DEFAULT_LIMIT == 5
    assert store.settings["output_dir"] == str(tmp_path / "downloads")
    assert not store.settings["videos"]


def test_add_persists_across_restarts(store, tmp_path):
    assert store.add_user("@NatGeo ")
    assert store.add_user("nasa")
    again = Store(store.path, tmp_path / "downloads")
    assert again.usernames() == ["natgeo", "nasa"]


def test_duplicates_ignored(store):
    assert store.add_user("natgeo")
    assert not store.add_user("NATGEO")
    assert store.usernames() == ["natgeo"]


@pytest.mark.parametrize("bad", ["", "@", "../evil", "a b", "x" * 31])
def test_invalid_rejected(store, bad):
    with pytest.raises(ValueError):
        store.add_user(bad)
    assert store.users == []


def test_remove(store, tmp_path):
    store.add_user("natgeo")
    store.add_user("nasa")
    assert store.remove_user("@natgeo")
    assert not store.remove_user("natgeo")
    assert Store(store.path, tmp_path).usernames() == ["nasa"]


def test_record_result(store):
    store.add_user("natgeo")
    store.record_result("natgeo", "ok, 3 new")
    user = store.users[0]
    assert user["last_status"] == "ok, 3 new" and user["last_run"]


def test_tags_on_and_caption_off_by_default(store):
    s = store.settings
    assert s["tags"] is True and s["caption"] is False


def test_settings_validated(store):
    store.update_settings(limit=0, videos="yes", tags="no")
    s = store.settings
    assert s["limit"] == 5 and s["videos"] is False and s["tags"] is True
    store.update_settings(limit=12, videos=True)
    s = store.settings
    assert s["limit"] == 12 and s["videos"] is True


def test_old_schedule_setting_dropped(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"settings": {"limit": 7, "schedule_time": "08:00"}}), encoding="utf-8")
    assert Store(path, tmp_path).settings == {**Store(tmp_path / "x.json", tmp_path).settings, "limit": 7}


def test_corrupt_file_backed_up(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text("{not json", encoding="utf-8")
    store = Store(path, tmp_path)
    assert store.users == []
    assert (tmp_path / "instakeep.json.bak").read_text(encoding="utf-8") == "{not json"


def test_bad_entries_dropped(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "ok_user"}, {"username": "../x"},
                                          "junk", {"username": "OK_USER"}]}), encoding="utf-8")
    assert Store(path, tmp_path).usernames() == ["ok_user"]


def test_other_process_changes_not_lost(store, tmp_path):
    other = Store(store.path, tmp_path / "downloads")  # e.g. a --run
    store.add_user("natgeo")
    other.record_result("natgeo", "ok, 1 new")
    store.add_user("nasa")  # must not wipe the other process's result
    store.reload()
    assert store.users[0]["last_status"] == "ok, 1 new"


def test_helpers():
    assert normalize_username(" @A.b_c ") == "a.b_c"


def test_remove_invalid_name_is_a_no_op(store):
    store.add_user("natgeo")
    assert store.remove_user("../etc") is False
    assert store.usernames() == ["natgeo"]


def test_text_from_file_is_cleaned(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "u", "last_status": "ok\x1b[2J"}]}),
                    encoding="utf-8")
    assert Store(path, tmp_path).users[0]["last_status"] == "ok[2J"


def test_all_posts_off_by_default(store):
    assert store.settings["all_posts"] is False


def test_record_result_adds_up_stats(store):
    from instakeep.store import STAT_FIELDS
    store.add_user("natgeo")
    run = {"runs": 1, "seconds": 10.0, "images": 3, "videos": 1, "media_count": 40,
           "last_seconds": 10.0, "last_images": 3}
    store.record_result("natgeo", "ok, 4 new", run_stats=run)
    store.record_result("natgeo", "ok, 1 new", run_stats={**run, "images": 1, "media_count": 41,
                                                          "last_seconds": 2.0, "last_images": 1})
    st = store.users[0]["stats"]
    assert set(st) == set(STAT_FIELDS)
    assert st["runs"] == 2 and st["seconds"] == 20 and st["images"] == 4 and st["videos"] == 2
    assert st["media_count"] == 41 and st["last_seconds"] == 2 and st["last_images"] == 1
    assert st["longest_seconds"] == 10  # the slower of the two runs
    store.record_result("natgeo", "ok, 0 new", run_stats={"runs": 1, "media_count": 0})
    assert store.users[0]["stats"]["media_count"] == 41  # 0 = unknown: keeps the old count


def test_longest_time_is_at_least_the_last_run(tmp_path):
    # A file saved before longest_seconds existed.
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "u", "stats": {"last_seconds": 7}}]}),
                    encoding="utf-8")
    assert Store(path, tmp_path).users[0]["stats"]["longest_seconds"] == 7


def test_bad_stats_in_file_become_zero(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "u", "stats": {
        "runs": -1, "seconds": "lots", "images": True, "videos": 2, "unknown": 5}}]}),
        encoding="utf-8")
    st = Store(path, tmp_path).users[0]["stats"]
    assert st["runs"] == 0 and st["seconds"] == 0 and st["images"] == 0 and st["videos"] == 2
    assert "unknown" not in st


# ------------------------------------------------------------- data version

def test_file_carries_the_data_version(store):
    from instakeep.store import STORE_VERSION
    store.add_user("natgeo")
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == STORE_VERSION


def test_file_without_a_version_is_upgraded(tmp_path):
    # A file from before versions existed (version 1).
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "natgeo", "last_run": "2026-01-01T08:00:00",
                                           "stats": {"runs": 2}}]}), encoding="utf-8")
    store = Store(path, tmp_path)
    assert not store.too_new
    user = store.users[0]
    assert user["stats"]["runs"] == 2
    assert (user["userid"], user["folder"], user["full_scan_done"], user["last_ok"]) == (None, None, False, None)


def test_migrations_run_from_the_files_version(tmp_path, monkeypatch):
    from instakeep import store as store_module
    seen = []
    monkeypatch.setattr(store_module, "STORE_VERSION", 3)
    monkeypatch.setattr(store_module, "MIGRATIONS", {1: lambda d: seen.append(1), 2: lambda d: seen.append(2)})
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")
    Store(path, tmp_path)
    assert seen == [2]


def _newer_file(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"version": 99, "settings": {"limit": 9},
                                "users": [{"username": "natgeo", "new_field": 1}]}), encoding="utf-8")
    return path


def test_newer_file_is_read_but_never_saved_over(tmp_path):
    from instakeep.store import NewerStoreError
    path = _newer_file(tmp_path)
    before = path.read_text(encoding="utf-8")
    store = Store(path, tmp_path)
    assert store.too_new and store.usernames() == ["natgeo"] and store.settings["limit"] == 9
    for write in (lambda: store.add_user("nasa"), lambda: store.remove_user("natgeo"),
                  lambda: store.update_settings(limit=3), lambda: store.record_result("natgeo", "ok"),
                  lambda: store.rename_user("natgeo", "x"), lambda: store.request_full_scan(["natgeo"])):
        with pytest.raises(NewerStoreError, match="newer version of InstaKeep"):
            write()
    assert path.read_text(encoding="utf-8") == before  # the newer fields are still there


def test_newer_file_is_noticed_by_a_running_process(store, tmp_path):
    from instakeep.store import NewerStoreError
    store.add_user("natgeo")
    store.check_writable()  # fine so far
    data = json.loads(store.path.read_text(encoding="utf-8"))
    store.path.write_text(json.dumps({**data, "version": 99}), encoding="utf-8")  # e.g. a newer --run
    with pytest.raises(NewerStoreError):
        store.check_writable()
    assert store.too_new


# ------------------------------------------------------ renames and full scans

def test_record_result_saves_last_ok_userid_and_full_scan(store):
    store.add_user("natgeo")
    store.record_result("natgeo", "not found")
    user = store.users[0]
    assert user["last_ok"] is None and user["userid"] is None and not user["full_scan_done"]
    store.record_result("natgeo", "ok, 1 new", ok=True, userid=787132, full_scan=True)
    user = store.users[0]
    assert user["last_ok"] == user["last_run"] and user["userid"] == 787132 and user["full_scan_done"]


def test_rename_keeps_the_old_folder(store, tmp_path):
    from instakeep.store import folder_name
    store.add_user("old_name")
    assert store.rename_user("old_name", "@New_Name")
    again = Store(store.path, tmp_path)
    assert again.usernames() == ["new_name"]
    assert folder_name(again.users[0]) == again.folder_of("new_name") == "old_name"
    assert store.rename_user("new_name", "newer")  # a second rename keeps the first folder
    assert store.folder_of("newer") == "old_name"


def test_rename_refuses_a_name_already_listed(store):
    store.add_user("a")
    store.add_user("b")
    assert not store.rename_user("a", "b")
    assert not store.rename_user("missing", "c")
    assert store.usernames() == ["a", "b"]
    with pytest.raises(ValueError):
        store.rename_user("a", "../evil")


def test_folder_of_an_unlisted_name_is_the_name(store):
    assert store.folder_of("someone") == "someone"


def test_request_full_scan(store):
    store.add_user("a")
    store.record_result("a", "ok", ok=True, full_scan=True)
    assert store.request_full_scan(["a", "not_listed", "../x"]) == 1
    assert store.users[0]["full_scan_done"] is False


def test_bad_new_fields_in_file_are_dropped(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"version": 2, "users": [{
        "username": "u", "folder": "../../etc", "userid": "12", "full_scan_done": "yes",
        "last_ok": 5}]}), encoding="utf-8")
    user = Store(path, tmp_path).users[0]
    assert (user["folder"], user["userid"], user["full_scan_done"], user["last_ok"]) == (None, None, False, None)
