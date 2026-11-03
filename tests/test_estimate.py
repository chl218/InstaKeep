import pytest

from instakeep import estimate as est
from instakeep.store import empty_stats, merge_stats


def user(name="u", **stats):
    return {"username": name, "stats": merge_stats(empty_stats(), stats)}


def settings(limit=5, all_posts=False, videos=False):
    return {"limit": limit, "all_posts": all_posts, "videos": videos}


@pytest.mark.parametrize("seconds,text", [
    (0, "0 s"), (44.6, "45 s"), (60, "1 min"), (200, "3 min 20 s"),
    (3600, "1 h"), (3900, "1 h 5 min"),
])
def test_format_duration(seconds, text):
    assert est.format_duration(seconds) == text


def test_users_never_downloaded_are_left_out():
    seen = user("seen", runs=1, seconds=10, posts=4, new_posts=1, images=1, image_seconds=1,
                queries=1, last_images=1)
    e = est.estimate([user("new"), seen], settings(limit=4))
    assert [u.username for u in e.users] == ["seen"] and e.no_data == ["new"]
    assert e.download_seconds == pytest.approx(e.users[0].seconds)


def test_without_history_estimate_user_uses_defaults_for_all_n_posts():
    u = est.estimate_user("u", user()["stats"], settings(limit=4))
    assert u.new_posts == 4 and u.known
    expected = (est.USER_SECONDS + (4 + est.MAX_PINNED) * est.DEFAULT_CHECK_SECONDS
                + 4 * est.DEFAULT_FILES_PER_POST * est.DEFAULT_IMAGE_SECONDS)
    assert u.seconds == pytest.approx(expected)


def test_history_sets_the_speed_and_the_expected_new_posts():
    # 1 run: 10 posts looked at, 2 new posts with 4 images that took 8 s.
    u = user(runs=1, seconds=20, posts=10, new_posts=2, images=4, image_seconds=8,
             queries=2, last_images=4)
    e = est.estimate([u], settings(limit=10))
    one = e.users[0]
    assert one.new_posts == pytest.approx(2)        # as many as the last download found
    per_post = 2 * 2.0                              # 2 files per post, 2 s per image
    check = (20 - 8 - est.USER_SECONDS) / 10        # leftover time per post looked at
    assert one.seconds == pytest.approx(est.USER_SECONDS + 13 * check + 2 * per_post)
    assert e.worst_seconds > e.total_seconds        # "up to" assumes all 10 are new


def test_videos_use_their_own_speed():
    u = user(runs=1, posts=2, new_posts=2, images=1, image_seconds=1,
             videos=1, video_seconds=9, last_images=1, last_videos=1)
    with_videos = est.estimate_user("u", u["stats"], settings(limit=2, videos=True), worst=True)
    without = est.estimate_user("u", u["stats"], settings(limit=2, videos=False), worst=True)
    assert with_videos.seconds > without.seconds


def test_all_posts_without_a_post_count_uses_the_posts_seen():
    # Instagram gives no post count without a login: media_count stays 0.
    u = user(runs=1, seconds=60, posts=12, new_posts=10, images=20, image_seconds=30,
             last_images=20)
    e = est.estimate([u], settings(all_posts=True))
    one = e.users[0]
    assert not e.unknown and e.download_seconds > 0
    assert one.checked_posts == 12
    assert one.new_posts == pytest.approx(2 + 10)  # 2 not on disk + 10 new since last


def test_all_posts_counts_whats_missing_from_disk():
    u = user(runs=1, posts=50, new_posts=50, images=50, image_seconds=50, media_count=80)
    one = est.estimate([u], settings(all_posts=True)).users[0]
    assert one.new_posts == pytest.approx(30) and one.checked_posts == 80


def test_rate_limit_pauses_from_instaloaders_limit():
    # 2 extra windows' worth of requests past the free first QUERY_LIMIT.
    assert est.pause_seconds(3 * est.QUERY_LIMIT, []) == pytest.approx(2 * est.QUERY_WINDOW)
    assert est.pause_seconds(est.QUERY_LIMIT, []) == 0


def test_rate_limit_pauses_from_history_when_larger():
    history = [merge_stats(empty_stats(), {"queries": 10, "pause_seconds": 100})]
    assert est.pause_seconds(5, history) == pytest.approx(50)  # 10 s per request seen before


def test_all_posts_after_a_full_pass_counts_only_the_new_posts():
    # A big profile: 3000 posts, fully downloaded once, 2 new posts last time.
    stats = dict(runs=2, seconds=4000, posts=3010, new_posts=3000, images=3000, image_seconds=3000,
                 queries=260, media_count=3000, last_images=2)
    full = est.estimate([{**user(**stats), "full_scan_done": False}], settings(all_posts=True))
    quick = est.estimate([{**user(**stats), "full_scan_done": True}], settings(all_posts=True))
    assert full.users[0].checked_posts == 3000
    assert quick.users[0].new_posts == pytest.approx(2)
    assert quick.users[0].checked_posts == pytest.approx(2 + est.MAX_PINNED + est.KNOWN_STREAK)
    assert quick.total_seconds < full.total_seconds / 100


def test_full_rescan_is_estimated_per_post():
    # Runs that stopped early make the per-run average tiny; the per-post rate stays right.
    stats = dict(runs=10, seconds=1000, posts=1000, new_posts=1000, images=1000, image_seconds=500,
                 media_count=1000, last_images=1)
    one = est.estimate([{**user(**stats), "full_scan_done": False}], settings(all_posts=True)).users[0]
    check = (1000 - 500 - est.USER_SECONDS * 10) / 1000
    assert one.seconds == pytest.approx(est.USER_SECONDS + 1000 * check + 1 * 0.5)


def test_constants_match_igdl():
    from igdl import downloader
    assert est.MAX_PINNED == downloader.MAX_PINNED
    assert est.KNOWN_STREAK == downloader.KNOWN_STREAK
