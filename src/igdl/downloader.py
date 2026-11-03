"""Thin wrapper around instaloader for downloading a user's posts.

This module does three things:
  - build_loader(): configure instaloader for our folder and file naming, the
    images-only default, the optional caption/metadata files, and sanitized output.
  - Rate-limit pauses: report them, let the user stop during one, and count
    Instagram requests and paused time (for download-time estimates).
  - download_user(): list a profile's posts, filter and limit them, save each one,
    write the caption's hashtags into the images' Tags, and optionally measure how
    long images and videos took (DownloadStats).
  - download_single_post(): the same for one post given by its link's shortcode.
  - username_for_id(): an account's current name from its ID (to follow renames).

instaloader does the Instagram API calls, paging, retries and file writing.
There is no login: only public profiles can be downloaded.
"""

from __future__ import annotations

import glob
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Callable

import instaloader
from instaloader.exceptions import (
    BadResponseException,
    PrivateProfileNotFollowedException,
    ProfileNotExistsException,
)

from .security import is_valid_username, strip_control
from .tags import extract_hashtags, tag_post_images


# --------------------------------------------------------------------------------------
# Rate-limit pauses
# --------------------------------------------------------------------------------------

# Pauses shorter than this aren't reported. instaloader uses the same cutoff.
PAUSE_NOTICE_SECONDS = 15


class DownloadStopped(Exception):
    """Raised when the user asks to stop while instaloader is paused for the rate limit."""


def format_pause(secs: float, now: datetime | None = None) -> str:
    """Message shown when instaloader pauses because of Instagram's rate limit."""
    until = (now or datetime.now()) + timedelta(seconds=secs)
    length = f"{round(secs)} s" if secs < 90 else f"{round(secs / 60)} min"
    return (f"Instagram rate limit: pausing {length} (until {until:%H:%M}). "
            "The download continues on its own.")


class _PauseAwareRateController(instaloader.RateController):
    """instaloader's rate limiter, plus a pause notice, a way to stop mid-pause,
    and counters for requests and paused time.

    instaloader calls wait_before_query() before every Instagram API request, and
    sleep() for every rate-limit pause: both when it slows itself down to stay
    under its limits and after Instagram answers 429. Overriding these is the
    documented way to change that behavior. Without on_pause/should_stop, it
    waits exactly like instaloader's own controller.
    """

    def __init__(self, context, on_pause=None, should_stop=None):
        super().__init__(context)
        self._on_pause = on_pause
        self._should_stop = should_stop
        self.queries = 0           # API requests so far (not media downloads from the CDN)
        self.paused_seconds = 0.0  # rate-limit pauses so far

    def wait_before_query(self, query_type: str) -> None:
        self.queries += 1
        super().wait_before_query(query_type)

    def sleep(self, secs: float) -> None:
        self.paused_seconds += secs
        if self._on_pause and secs > PAUSE_NOTICE_SECONDS:
            self._on_pause(secs)
        if self._should_stop is None:
            super().sleep(secs)
            return
        # Sleep in short steps so a Stop request doesn't wait out the whole pause.
        deadline = time.monotonic() + secs
        while (left := deadline - time.monotonic()) > 0:
            if self._should_stop():
                raise DownloadStopped()
            time.sleep(min(left, 0.5))


# --------------------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------------------

# Where posts go and what their files are called. These are a fixed contract:
# whether a post is already downloaded is worked out only from these names, so
# changing them makes every post download again. tests/test_cli.py pins them.
# {target} is the folder name: the lowercase username (or, after a rename, the old one).
# e.g. natgeo_2026-11-01_23-53-04_DfN9Oosk9s2. Carousel items get _1, _2, ...
DIRNAME_PATTERN = "{target}"
FILENAME_PATTERN = "{target}_{date_utc:%Y-%m-%d_%H-%M-%S}_{shortcode}"

def build_loader(
    output_dir: Path,
    videos: bool = False,
    caption: bool = False,
    images: bool = True,
    metadata: bool = False,
    quiet: bool = False,
    on_pause: Callable[[float], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> instaloader.Instaloader:
    """Create an Instaloader that saves posts to output_dir/<username>/.

    videos=False (default): only photos. Video posts are skipped by download_user,
        and video slides inside carousels are skipped here.
    images=False: no photos. Image posts are skipped by download_user, and image
        slides inside carousels (and video cover images) are skipped here.
        At least one of images and videos must be on (ValueError otherwise).
    caption=True: save <name>.txt with the caption. (Hashtag Tags are a separate
        option: download_user's `tags`.)
    metadata=True: save <name>.json with the post's full data.

    on_pause(seconds) is called when a rate-limit pause starts (longer than
    PAUSE_NOTICE_SECONDS). It works even with quiet=True, which hides instaloader's
    own message about the pause. should_stop() is checked during pauses; if it
    returns True, the pause ends with DownloadStopped.
    """
    if not (images or videos):
        raise ValueError("nothing to download: turn on images or videos")
    loader = instaloader.Instaloader(
        # Always our controller, so requests and pauses are counted for DownloadStats.
        rate_controller=lambda ctx: _PauseAwareRateController(ctx, on_pause, should_stop),
        # instaloader fills {target} with the folder name passed to download_post().
        dirname_pattern=str(Path(output_dir) / DIRNAME_PATTERN),
        filename_pattern=FILENAME_PATTERN,
        download_pictures=images,
        # Turning off both video files and video thumbnails makes instaloader skip
        # video slides in carousels entirely, instead of saving their cover image.
        # A cover image is a picture, so it's also skipped with images off.
        download_videos=videos,
        download_video_thumbnails=videos and images,
        download_geotags=False,   # would need an extra request per post
        download_comments=False,  # would need many extra requests per post
        save_metadata=metadata,   # <name>.json with the post's full data
        compress_json=False,      # plain .json, not .json.xz
        # <name>.txt with the caption; an empty pattern disables the file.
        post_metadata_txt_pattern="{caption}" if caption else "",
        quiet=quiet,
    )
    _install_safe_logging(loader.context)
    return loader


def _install_safe_logging(context: instaloader.InstaloaderContext) -> None:
    """Strip terminal control characters from instaloader's output.

    instaloader prints the start of each caption while it downloads. A caption is
    written by the post's author and could hide ANSI escape codes that change the
    terminal (title, colors, clearing the screen). We wrap its two print functions.
    """
    raw_log, raw_error = context.log, context.error

    def log(*msg, sep="", end="\n", flush=False):
        raw_log(*(strip_control(str(m)) for m in msg), sep=sep, end=end, flush=flush)

    def error(msg, repeat_at_end=True):
        raw_error(strip_control(str(msg)), repeat_at_end=repeat_at_end)

    context.log = log
    context.error = error


# --------------------------------------------------------------------------------------
# Downloading
# --------------------------------------------------------------------------------------

# Instagram lets a profile pin up to 3 posts, which it always lists first.
MAX_PINNED = 3

# With stop_at_known, how many posts in a row already on disk end an "all posts"
# run. More than one, so a gap left by an interrupted run isn't taken as the end.
KNOWN_STREAK = 3

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4"}


@dataclass
class DownloadStats:
    """Measurements of one download_user() run, filled in as it goes.

    Only posts that saved at least one new file count towards images/videos and
    their seconds; posts already on disk are skipped quickly and would make the
    per-file times look shorter than they are.
    """
    media_count: int | None = None  # the profile's total number of posts
    posts: int = 0                  # posts looked at (new or already on disk)
    new_posts: int = 0              # posts that saved at least one new file
    images: int = 0                 # new image files
    image_seconds: float = 0.0      # time spent saving them
    videos: int = 0                 # new video files
    video_seconds: float = 0.0
    queries: int = 0                # Instagram API requests (what the rate limit counts)
    pause_seconds: float = 0.0      # rate-limit pauses during this run
    userid: int | None = None       # the account's ID, which stays the same after a rename
    complete: bool = False          # True: every post was looked at (no limit, no early stop)


def _post_files(folder: Path, basename: str) -> set[str]:
    """Names of the files saved for one post (<basename>.jpg, <basename>_2.mp4, ...)."""
    if not folder.is_dir():
        return set()
    # escape(): the name comes from Instagram data, so treat it literally, not as a pattern.
    return {p.name for p in folder.glob(glob.escape(basename) + "*")}


def _has_media(names: set[str]) -> bool:
    """True if any of these file names is an image or a video."""
    return any(Path(n).suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES for n in names)


def _count_new_files(stats: DownloadStats, new_files: set[str], seconds: float) -> None:
    """Add one post's new files to stats, splitting its time between images and videos."""
    images = sum(Path(n).suffix.lower() in IMAGE_SUFFIXES for n in new_files)
    videos = sum(Path(n).suffix.lower() in VIDEO_SUFFIXES for n in new_files)
    if not images + videos:
        return  # only .txt/.json, or nothing: the post was already downloaded
    stats.new_posts += 1
    stats.images += images
    stats.videos += videos
    # A carousel can mix both; share the post's time by number of files.
    stats.image_seconds += seconds * images / (images + videos)
    stats.video_seconds += seconds * videos / (images + videos)


def download_user(
    loader: instaloader.Instaloader,
    username: str,
    limit: int | None = None,
    log: Callable[[str], None] = print,
    should_stop: Callable[[], bool] = lambda: False,
    tags: bool = False,
    stats: DownloadStats | None = None,
    folder_name: str | None = None,
    stop_at_known: bool = False,
) -> int:
    """Download a user's posts, newest first. Returns how many were saved.

    The files go in <output_dir>/<folder_name>/, named after folder_name (see
    FILENAME_PATTERN). folder_name defaults to the lowercase username; InstaKeep
    passes the old name after an account was renamed. It must be a valid username.

    stop_at_known=True (only used without a limit): stop after KNOWN_STREAK posts
    in a row that are already on disk, not counting the first MAX_PINNED posts
    (pinned posts can be old). For profiles that were fully downloaded before.

    tags=True writes each caption's #hashtags into the post's images' Tags
    (independent of the caption .txt option in build_loader).

    stats, if given, is filled in with file counts, timings, requests and pauses,
    also when the run ends early with an error.

    should_stop is checked before each post; returning True ends the run early
    (the GUI's Stop button uses it). The post being saved is always finished first.
    To also stop during rate-limit pauses, pass the same function to build_loader.

    Video posts are skipped unless the loader was built with videos=True, and
    --limit counts only the posts that are kept. Pinned posts are downloaded like
    any other, but --limit picks the newest posts by date, so old pinned posts
    don't take up slots.
    """
    count = 0
    # Requests and pauses are counted by the loader's rate controller across every
    # user it downloads; remember where it stood to get this run's share.
    controller = getattr(loader.context, "_rate_controller", None)
    queries_before = getattr(controller, "queries", 0)
    paused_before = getattr(controller, "paused_seconds", 0.0)
    try:
        # One request: profile info (id, privacy, post count).
        profile = instaloader.Profile.from_username(loader.context, username)
        if stats is not None:
            stats.media_count = profile.mediacount
            stats.userid = getattr(profile, "userid", None)

        # Fail early with a clear message rather than an empty download.
        if profile.is_private:
            raise PrivateProfileNotFollowedException(
                f"Profile {profile.username} is private, so its posts can't be downloaded."
            )

        # Settings chosen in build_loader.
        include_videos = loader.download_videos
        include_images = loader.download_pictures
        # The folder name becomes part of a path: same check as a username.
        target = (folder_name or profile.username).lower()
        if not is_valid_username(target):
            raise ValueError(f"unusable folder name: {target!r}")
        # build_loader set dirname_pattern to <output_dir>/{target}.
        folder = Path(loader.dirname_pattern).parent / target
        stop_early = stop_at_known and limit is None
        known_in_a_row = 0
        seen = 0  # posts from the feed so far, for skipping the pinned ones

        # Work out the total for the "[i/total]" progress lines.
        known = profile.mediacount
        if limit is not None:
            total = str(limit) if known is None else str(min(limit, known))
        elif include_videos and include_images and known is not None:
            total = str(known)
        else:
            total = "?"  # unknown until we've seen which posts are videos
        if include_videos and include_images:
            kind = "post(s)"
        else:
            kind = "image post(s)" if include_images else "video and carousel post(s)"
        log(f"Downloading {total} {kind} from @{profile.username}")

        # Build the list of posts lazily. get_posts() fetches pages of ~12 posts from
        # Instagram only as the loop below asks for them, so --limit avoids fetching more.
        posts = profile.get_posts()
        if not include_videos:
            # Images-only: drop video and reel posts before --limit counts anything.
            posts = (p for p in posts if not p.is_video)
        if not include_images:
            # Videos-only: drop single-image posts. Carousels stay, since they can
            # hold videos; their image slides are skipped by the loader.
            posts = (p for p in posts if getattr(p, "typename", None) != "GraphImage")
        if limit is not None:
            # Up to MAX_PINNED pinned posts come first regardless of date. Read that many
            # extra posts, then keep the newest `limit` by date.
            candidates = list(islice(posts, limit + MAX_PINNED))
            posts = sorted(candidates, key=lambda p: p.date_utc, reverse=True)[:limit]

        finished = True  # False if the loop ends before the last post
        for post in posts:
            if should_stop():
                raise DownloadStopped()
            count += 1
            seen += 1
            log(f"[{count}/{total}] {post.date_utc:%Y-%m-%d} {post.shortcode}")
            basename = None
            if stats is not None or tags or stop_early:
                basename = loader.format_filename(post, target=target)
            before = _post_files(folder, basename) if basename else set()
            if stats is not None:
                stats.posts += 1
                started = time.monotonic()
                paused_at_start = getattr(controller, "paused_seconds", 0.0)
            # Saves the media (+ .txt/.json). Files that already exist are skipped,
            # which is what makes re-running after an interruption safe.
            loader.download_post(post, target=target)
            if stats is not None:
                # Rate-limit pauses are measured separately, so leave them out here.
                paused = getattr(controller, "paused_seconds", 0.0) - paused_at_start
                seconds = max(0.0, time.monotonic() - started - paused)
                _count_new_files(stats, _post_files(folder, basename) - before, seconds)

            if tags:
                # "#portrait" in the caption -> "#portrait" in each image's Tags.
                # Also runs for images saved earlier, so a re-run adds missing tags.
                hashtags = extract_hashtags(post.caption)
                if hashtags and tag_post_images(folder, basename, hashtags):
                    log(f"    tags: {'; '.join(hashtags)}")

            if stop_early and seen > MAX_PINNED:
                known_in_a_row = known_in_a_row + 1 if _has_media(before) else 0
                if known_in_a_row >= KNOWN_STREAK:
                    log("Reached posts downloaded earlier; stopping here. "
                        "(A full re-scan looks at every post again.)")
                    finished = False
                    break
        if stats is not None:
            stats.complete = finished and limit is None
    except DownloadStopped:
        # From the check above, or from a rate-limit pause (see build_loader).
        log("Stopped.")
    finally:
        if stats is not None:
            stats.queries += getattr(controller, "queries", 0) - queries_before
            stats.pause_seconds += getattr(controller, "paused_seconds", 0.0) - paused_before
    return count


@dataclass
class PostResult:
    """What download_single_post() did."""
    owner: str           # the post's account (lowercase), e.g. "natgeo"
    saved: bool          # False if skipped: a video post while videos are off
    new_files: int = 0   # new image/video files written


def download_single_post(
    loader: instaloader.Instaloader,
    shortcode: str,
    log: Callable[[str], None] = print,
    tags: bool = False,
    folder_for: Callable[[str], str] | None = None,
) -> PostResult:
    """Download one post (from security.parse_post_url) into output_dir/<owner>/.

    The files get the same names download_user() gives them, so a later run for
    that account skips this post. Video posts are skipped unless the loader was
    built with videos=True. A post that is gone, or whose account is private,
    raises BadResponseException (see cli.describe_error).

    folder_for(owner) gives the folder name for an account (InstaKeep keeps a
    renamed account's old folder); without it, the folder is the owner's name.
    """
    # One request: the post's data, including its owner.
    post = instaloader.Post.from_shortcode(loader.context, shortcode)
    owner = post.owner_username
    # The owner name comes from Instagram and becomes a folder name.
    if not is_valid_username(owner):
        raise BadResponseException(f"Instagram returned an unusable account name for post {shortcode}.")
    owner = owner.lower()

    if post.is_video and not loader.download_videos:
        log(f"@{owner} {shortcode} is a video post. Tick Videos to download it.")
        return PostResult(owner, saved=False)
    if getattr(post, "typename", None) == "GraphImage" and not loader.download_pictures:
        log(f"@{owner} {shortcode} is an image post. Tick Images to download it.")
        return PostResult(owner, saved=False)

    log(f"Downloading {shortcode} ({post.date_utc:%Y-%m-%d}) from @{owner}")
    target = folder_for(owner).lower() if folder_for else owner
    if not is_valid_username(target):
        raise ValueError(f"unusable folder name: {target!r}")
    folder = Path(loader.dirname_pattern).parent / target
    basename = loader.format_filename(post, target=target)
    before = _post_files(folder, basename)
    loader.download_post(post, target=target)  # files already on disk are skipped
    new = {n for n in _post_files(folder, basename) - before
           if Path(n).suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES}
    if tags:
        hashtags = extract_hashtags(post.caption)
        if hashtags and tag_post_images(folder, basename, hashtags):
            log(f"    tags: {'; '.join(hashtags)}")
    return PostResult(owner, saved=True, new_files=len(new))


def username_for_id(loader: instaloader.Instaloader, userid: int) -> str | None:
    """The account's current username (lowercase), or None if Instagram has no
    such account or won't say. Used to spot a renamed account.

    Without a login, Instagram may refuse this lookup; that also gives None.
    Rate-limit and connection errors are raised as usual.
    """
    try:
        profile = instaloader.Profile.from_id(loader.context, userid)
    except ProfileNotExistsException:
        return None
    name = profile.username
    # The name comes from Instagram and may become a list entry and a folder name.
    return name.lower() if is_valid_username(name) else None
