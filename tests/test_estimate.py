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


def test_never_downloaded_uses_defaults_for_all_n_posts():
    e = est.estimate([user()], settings(limit=4))
    u = e.users[0]
    assert u.new_posts == 4 and u.known
    expected = (est.USER_SECONDS + (4 + est.MAX_PINNED) * est.DEFAULT_CHECK_SECONDS
                + 4 * est.DEFAULT_FILES_PER_POST * est.DEFAULT_IMAGE_SECONDS)
    assert u.seconds == pytest.approx(expected)
    assert e.pause_seconds == 0  # a handful of requests is far below the limit


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


def test_all_posts_unknown_until_first_download():
    e = est.estimate([user()], settings(all_posts=True))
    assert e.unknown == ["u"] and e.download_seconds == 0


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
