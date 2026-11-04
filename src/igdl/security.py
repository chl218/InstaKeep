"""Small helpers for handling untrusted input and text safely.

Everything here uses only the standard library and has no network or file
access, so it can run before setup is finished (instakeep.py uses it) and is
easy to test (see tests/test_security.py). Used by cli.py, downloader.py and
the instakeep app.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path

# Instagram usernames: letters, digits, "." and "_", up to 30 chars.
# Anything else (slashes, "..") is rejected, which also rules out path tricks
# like "../evil" when the name is used as a folder.
_USERNAME_RE = re.compile(r"[A-Za-z0-9._]{1,30}")

# Characters removed before text from Instagram is printed or shown:
#   - C0/C1 control chars except tab (\x09) and newline (\x0a). Covers ESC (\x1b),
#     which starts ANSI escape sequences, and BEL (\x07).
#   - Unicode bidirectional overrides and isolates (U+202A-U+202E, U+2066-U+2069),
#     which can make a caption or log line display differently from what it says.
_UNSAFE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")

# A post link: instagram.com/p/<code>, /reel/<code>, /reels/<code> or /tv/<code>,
# optionally after the account name (instagram.com/natgeo/p/<code>). Anything after
# the code (?igsh=..., ?srtk=..., #...) is ignored. Only the code is used afterwards,
# so nothing else from the pasted text reaches a request or a file name.
_POST_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?"
    r"(?:p|reels?|tv)/([A-Za-z0-9_-]{5,64})/?(?:[?#].*)?",
    re.IGNORECASE,
)


def parse_post_url(text: str) -> str:
    """'https://www.instagram.com/p/EXAMPLE_POST/?igsh=...' -> 'EXAMPLE_POST'.

    Raises ValueError if the text isn't an Instagram post or reel link.
    """
    match = _POST_URL_RE.fullmatch(text.strip())
    if not match:
        raise ValueError("Not an Instagram post link. It should look like "
                         "https://www.instagram.com/p/... or https://www.instagram.com/reel/...")
    return match.group(1)


# Stricter than _POST_URL_RE, for links read from a file (the Files tab): https only,
# host exactly instagram.com or www.instagram.com (no "m.", userinfo, port or
# look-alike host), and an optional query or fragment from a small safe character set.
# The whole line must match, so trailing text rejects it.
_STRICT_POST_URL_RE = re.compile(
    r"https://(?:www\.)?instagram\.com/(?:[A-Za-z0-9._]{1,30}/)?"
    r"(?:p|reels?|tv)/([A-Za-z0-9_-]{5,64})/?(?:[?#][A-Za-z0-9_=&%.\-]*)?",
    re.IGNORECASE,
)

ENTRIES_MAX_BYTES = 64 * 1024  # an input file bigger than this is refused
ENTRIES_MAX_LINES = 100        # so is one with more non-blank lines than this
ENTRIES_REJECT_SHOWN = 80      # rejected lines are cut to this many characters


def parse_post_url_strict(text: str) -> str:
    """Like parse_post_url, but only https://instagram.com or https://www.instagram.com.

    'https://www.instagram.com/p/EXAMPLE_POST/?igsh=x' -> 'EXAMPLE_POST'.
    Raises ValueError for anything else (http, no scheme, m.instagram.com,
    instagram.com@evil.com, instagram.com.evil.com, a port, trailing text...).
    """
    match = _STRICT_POST_URL_RE.fullmatch(text.strip())
    if not match:
        raise ValueError("Not an https://www.instagram.com post link.")
    return match.group(1)


def post_url(shortcode: str) -> str:
    """The link shown for a shortcode: rebuilt, never the text that was pasted."""
    return f"https://www.instagram.com/p/{shortcode}/"


def read_entries_file(path: str | Path) -> str:
    """The text of an input file of usernames and post links, after safety checks.

    Raises ValueError (with a message fit for the user) unless it is a regular
    .txt file of at most ENTRIES_MAX_BYTES bytes, valid UTF-8 (a BOM is fine),
    with no control characters and at most ENTRIES_MAX_LINES non-blank lines.
    """
    path = Path(path)
    if path.suffix.lower() != ".txt":
        raise ValueError("Only plain .txt files are accepted (not CSV, JSON or other formats).")
    try:
        if not path.is_file():
            raise ValueError("That is not a file.")
        with path.open("rb") as f:
            raw = f.read(ENTRIES_MAX_BYTES + 1)
    except OSError as e:
        raise ValueError(f"Couldn't read the file: {e.strerror or type(e).__name__}.") from e
    if len(raw) > ENTRIES_MAX_BYTES:
        raise ValueError(f"The file is bigger than {ENTRIES_MAX_BYTES // 1024} KB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError("The file isn't valid UTF-8 text.") from e
    text = text.replace("\r\n", "\n")
    if strip_control(text) != text:
        raise ValueError("The file contains control characters.")
    if sum(1 for line in text.split("\n") if line.strip()) > ENTRIES_MAX_LINES:
        raise ValueError(f"The file has more than {ENTRIES_MAX_LINES} lines.")
    return text


def parse_entries(text: str) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Sort the lines of an input file into (usernames, links, rejected).

    A line is a link (strict https post link) or a username (normalized to
    lowercase, a leading "@" allowed); anything else, such as a comment, a CSV
    row or JSON, is rejected. Blank lines are ignored and duplicates dropped.
    links are (shortcode, rebuilt URL); rejected lines are cut to a short length.
    """
    usernames: list[str] = []
    links: list[tuple[str, str]] = []
    rejected: list[str] = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            code = parse_post_url_strict(line)
        except ValueError:
            pass
        else:
            if all(code != c for c, _url in links):
                links.append((code, post_url(code)))
            continue
        try:
            name = normalize_username(line)
        except ValueError:
            rejected.append(line[:ENTRIES_REJECT_SHOWN])
            continue
        if name not in usernames:
            usernames.append(name)
    return usernames, links, rejected


def is_valid_username(name: str) -> bool:
    """True if name could be an Instagram username."""
    return bool(_USERNAME_RE.fullmatch(name))


def normalize_username(name: str) -> str:
    """'  @NatGeo ' -> 'natgeo'. Raises ValueError if it can't be a username.

    Instagram usernames are case-insensitive and instaloader saves into the
    lowercase folder name, so every caller works with the lowercase form.
    """
    name = name.strip().lstrip("@").lower()
    if not is_valid_username(name):
        raise ValueError("Not a valid Instagram username (letters, digits, '.' and '_', max 30).")
    return name


def strip_control(text: str) -> str:
    """Remove the characters matched by _UNSAFE_RE so text is safe to print."""
    return _UNSAFE_RE.sub("", text)


def describe_unexpected(e: BaseException) -> str:
    """Message for an error nothing else explains (a bug, a full disk...).

    A one-line summary, then the full traceback, so the problem can be tracked
    down from the window's log or the --run log file. Control characters are
    stripped because the message can contain text from Instagram.
    """
    trace = "".join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip()
    return strip_control(f"unexpected error ({type(e).__name__}): {e}\n{trace}")


def safe_console() -> None:
    """Print "?" for characters the console can't show instead of crashing.

    Captions and hashtags can be in any language. On a console whose encoding
    can't show a character (e.g. Korean on a cp1252 console), printing it would
    raise UnicodeEncodeError mid-download. Files always keep the real text.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # None (pythonw) or not a real text stream
            pass
