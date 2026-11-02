"""Small helpers for handling untrusted input and text safely.

Everything here uses only the standard library and has no network or file
access, so it can run before setup is finished (main-program.py uses it) and is
easy to test (see tests/test_security.py). Used by cli.py, downloader.py and
the instakeep app.
"""

from __future__ import annotations

import re
import sys
import traceback

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
