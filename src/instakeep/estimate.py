"""Estimate how long a download will take, from the records of earlier downloads.

Each user's records (store.STAT_FIELDS) say how long their images and videos
took, how many files a post has, how many Instagram requests a post needs and
how much time went to rate-limit pauses. A user with no finished download yet
has nothing to go on, so they are left out of the estimate (Estimate.no_data).
The DEFAULT_* values fill in what a user's records don't say yet, such as the
speed of videos for a user who has only had images downloaded.

Rate limit: instaloader allows about QUERY_LIMIT requests per QUERY_WINDOW
seconds and pauses once it reaches that. One run shares one loader across all
its users, so the requests of every user count together.

Everything here is a pure function: no files, no network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# instaloader's own limit (RateController): 200 requests of a kind per 11 minutes.
QUERY_LIMIT = 200
QUERY_WINDOW = 660            # seconds
POSTS_PER_PAGE = 12           # posts Instagram returns per request when listing a profile
MAX_PINNED = 3                # with a limit, igdl reads this many extra posts

# Used where a user's records don't say yet.
DEFAULT_IMAGE_SECONDS = 1.5   # per image file
DEFAULT_VIDEO_SECONDS = 8.0   # per video file
DEFAULT_FILES_PER_POST = 1.5  # carousels have several files
DEFAULT_VIDEO_SHARE = 0.25    # share of files that are videos, with videos on
DEFAULT_CHECK_SECONDS = 0.5   # per post looked at, on top of its files (incl. already on disk)
DEFAULT_QUERIES_PER_POST = 1 / POSTS_PER_PAGE
USER_SECONDS = 2.0            # per user: looking up the profile
USER_QUERIES = 1              # per user: the profile lookup


@dataclass
class UserEstimate:
    username: str
    new_posts: float      # posts expected to need downloading
    checked_posts: float  # posts looked at, including ones already on disk
    seconds: float        # time downloading, without rate-limit pauses
    queries: float        # Instagram requests
    known: bool = True    # False: post count unknown (all posts, profile size not recorded)


@dataclass
class Estimate:
    users: list[UserEstimate] = field(default_factory=list)
    download_seconds: float = 0.0
    pause_seconds: float = 0.0
    worst_seconds: float = 0.0     # if every post in range is new (same as total for all posts)
    runs_used: int = 0             # past downloads the estimate is based on
    no_data: list[str] = field(default_factory=list)  # never downloaded: left out

    @property
    def total_seconds(self) -> float:
        return self.download_seconds + self.pause_seconds

    @property
    def unknown(self) -> list[str]:
        return [u.username for u in self.users if not u.known]


def _ratio(part: float, whole: float, default: float) -> float:
    return part / whole if whole > 0 else default


def _seconds_per_post(stats: dict, videos: bool) -> float:
    """Download time of one new post's files, from the user's records."""
    files = stats["images"] + stats["videos"]
    files_per_post = _ratio(files, stats["new_posts"], DEFAULT_FILES_PER_POST)
    image_s = _ratio(stats["image_seconds"], stats["images"], DEFAULT_IMAGE_SECONDS)
    video_s = _ratio(stats["video_seconds"], stats["videos"], DEFAULT_VIDEO_SECONDS)
    if not videos:
        video_share = 0.0
    elif stats["videos"]:
        video_share = stats["videos"] / files
    else:
        video_share = DEFAULT_VIDEO_SHARE  # never downloaded videos for this user yet
    return files_per_post * ((1 - video_share) * image_s + video_share * video_s)


def _check_seconds(stats: dict) -> float:
    """Time per post looked at, beyond downloading its files (listing, skipping, tags)."""
    other = (stats["seconds"] - stats["image_seconds"] - stats["video_seconds"]
             - stats["pause_seconds"] - USER_SECONDS * stats["runs"])
    return max(0.0, _ratio(other, stats["posts"], DEFAULT_CHECK_SECONDS))


def _expected_new_posts(stats: dict, limit: int | None, worst: bool) -> tuple[float, float, bool]:
    """(new posts, posts looked at, known) for one user."""
    files_per_post = _ratio(stats["images"] + stats["videos"], stats["new_posts"],
                            DEFAULT_FILES_PER_POST)
    # New posts since the last download: as many as that download found.
    since_last = (stats["last_images"] + stats["last_videos"]) / files_per_post
    if limit is not None:
        checked = limit + MAX_PINNED
        if worst or not stats["runs"]:
            return float(limit), checked, True
        return min(float(limit), since_last), checked, True
    # All posts: everything not on disk yet, plus what's new since the last download.
    profile_posts = _profile_posts(stats)
    if not profile_posts:
        return 0.0, 0.0, False
    missing = max(0.0, profile_posts - stats["new_posts"])
    return missing + since_last, profile_posts, True


def _profile_posts(stats: dict) -> float:
    """The profile's post count. Without a login Instagram doesn't say, and a run
    over all posts that hasn't finished yet doesn't know it either. Then assume
    at least as many posts as earlier downloads saw (0 if never downloaded)."""
    if stats["media_count"]:
        return float(stats["media_count"])
    if not stats["runs"]:
        return 0.0
    return max(float(stats["new_posts"]), stats["posts"] / stats["runs"])


def estimate_user(username: str, stats: dict, settings: dict, worst: bool = False) -> UserEstimate:
    """How long one user should take with these settings (rate-limit pauses excluded)."""
    limit = None if settings["all_posts"] else settings["limit"]
    new, checked, known = _expected_new_posts(stats, limit, worst)
    seconds = (USER_SECONDS + checked * _check_seconds(stats)
               + new * _seconds_per_post(stats, settings["videos"]))
    queries_per_post = _ratio(stats["queries"], stats["posts"], DEFAULT_QUERIES_PER_POST)
    queries = USER_QUERIES + checked * queries_per_post
    return UserEstimate(username, new, checked, seconds if known else 0.0, queries, known)


def pause_seconds(queries: float, history: list[dict]) -> float:
    """Expected rate-limit pauses for a run making `queries` requests.

    Two views, and the larger wins: instaloader's limit (every QUERY_LIMIT requests
    past the first QUERY_LIMIT cost one QUERY_WINDOW), and how much pausing earlier
    downloads saw per request (this includes Instagram's own 429 blocks).
    """
    by_limit = max(0.0, queries - QUERY_LIMIT) / QUERY_LIMIT * QUERY_WINDOW
    seen_queries = sum(s["queries"] for s in history)
    seen_pauses = sum(s["pause_seconds"] for s in history)
    by_history = queries * _ratio(seen_pauses, seen_queries, 0.0)
    return max(by_limit, by_history)


def estimate(users: list[dict], settings: dict) -> Estimate:
    """Estimate a run over `users` (store user entries) with these settings.

    Users without a finished download are left out and listed in `no_data`.
    """
    no_data = [u["username"] for u in users if not u["stats"]["runs"]]
    users = [u for u in users if u["stats"]["runs"]]
    history = [u["stats"] for u in users]
    result = Estimate(runs_used=sum(s["runs"] for s in history), no_data=no_data)
    worst_download = 0.0
    worst_queries = 0.0
    for user in users:
        typical = estimate_user(user["username"], user["stats"], settings)
        worst = estimate_user(user["username"], user["stats"], settings, worst=True)
        result.users.append(typical)
        result.download_seconds += typical.seconds
        worst_download += worst.seconds
        worst_queries += worst.queries
    queries = sum(u.queries for u in result.users if u.known)
    result.pause_seconds = pause_seconds(queries, history)
    result.worst_seconds = worst_download + pause_seconds(worst_queries, history)
    return result


def format_duration(seconds: float) -> str:
    """45 -> '45 s', 200 -> '3 min 20 s', 3900 -> '1 h 5 min'."""
    seconds = max(0, round(seconds))
    if seconds < 60:
        return f"{seconds} s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def ceil_queries(queries: float) -> int:
    """Requests as a whole number, for display."""
    return math.ceil(queries)
