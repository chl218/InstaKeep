"""Write a post's hashtags into its image files' Tags.

Windows Explorer shows these under Properties -> Details -> Tags, and you can
search for them (e.g. `tags:#portrait`). They're stored in the JPEG's EXIF
XPKeywords field, which is where Windows itself saves tags.

piexif inserts the EXIF data without re-encoding the image, so quality is unchanged.
Only .jpg files are tagged; videos (.mp4) don't use EXIF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import piexif

# A "#" followed by letters, digits or "_" (any language). The tag ends at the first
# other character, so "#portrait." gives "#portrait" and "#a#b" gives "#a", "#b".
_HASHTAG_RE = re.compile(r"#\w+")
# Windows separates multiple tags with ";".
_SEPARATOR = ";"


def extract_hashtags(caption: str | None) -> list[str]:
    """Hashtags in a caption, in order, without duplicates.

    "Wow this #portrait is awesome #Portrait #sky" -> ["#portrait", "#sky"].
    Duplicates are matched ignoring case; the first spelling is kept.
    """
    if not caption:
        return []
    seen: set[str] = set()
    tags = []
    for tag in _HASHTAG_RE.findall(caption):
        key = tag.casefold()
        if key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


def _encode_xp(text: str) -> tuple[int, ...]:
    # XP* fields are UTF-16LE text ending in a 2-byte null, stored as a byte list.
    return tuple((text + "\x00").encode("utf-16-le"))


def _decode_xp(value) -> str:
    return bytes(value).decode("utf-16-le", errors="replace").rstrip("\x00")


def read_tags(path: Path) -> list[str]:
    """Tags currently stored in a JPEG (empty list if none)."""
    try:
        value = piexif.load(str(path))["0th"].get(piexif.ImageIFD.XPKeywords)
    except Exception:  # no EXIF block, or EXIF piexif can't parse
        return []
    if not value:
        return []
    return [t for t in _decode_xp(value).split(_SEPARATOR) if t]


def write_tags(path: Path, tags: list[str]) -> bool:
    """Store tags in a JPEG's EXIF. Returns True if the file was changed.

    Files that already have exactly these tags are left alone, so re-running a
    download doesn't rewrite every image. The file's modified date (which
    instaloader sets to the post's date) is kept.
    """
    if not tags or read_tags(path) == tags:
        return False
    try:
        exif = piexif.load(str(path))
    except Exception:
        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    exif["0th"][piexif.ImageIFD.XPKeywords] = _encode_xp(_SEPARATOR.join(tags))

    stat = path.stat()
    piexif.insert(piexif.dump(exif), str(path))  # rewrites only the EXIF segment
    os.utime(path, (stat.st_atime, stat.st_mtime))  # keep the post's date
    return True


def tag_post_images(folder: Path, basename: str, tags: list[str]) -> int:
    """Tag every image of one post. Returns how many files were changed.

    A single-image post is saved as <basename>.jpg; a carousel as <basename>_1.jpg,
    <basename>_2.jpg, ...
    """
    if not tags:
        return 0
    files = [folder / f"{basename}.jpg", *sorted(folder.glob(f"{basename}_*.jpg"))]
    changed = 0
    for f in files:
        if not f.is_file():
            continue
        try:
            changed += write_tags(f, tags)
        except Exception:  # noqa: BLE001 - a JPEG piexif can't rewrite keeps its file, just untagged
            continue
    return changed
