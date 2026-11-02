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


def test_bad_stats_in_file_become_zero(tmp_path):
    path = tmp_path / "instakeep.json"
    path.write_text(json.dumps({"users": [{"username": "u", "stats": {
        "runs": -1, "seconds": "lots", "images": True, "videos": 2, "unknown": 5}}]}),
        encoding="utf-8")
    st = Store(path, tmp_path).users[0]["stats"]
    assert st["runs"] == 0 and st["seconds"] == 0 and st["images"] == 0 and st["videos"] == 2
    assert "unknown" not in st
