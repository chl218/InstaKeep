"""The window's preview of the image downloaded most recently in this session (Pillow).

tkinter can't show JPEG, so images are opened with Pillow. Loading (decoding a
large photo) happens on a background thread: load_preview() returns a small
copy that the Tk thread then fits to the panel (fit()) and turns into a
PhotoImage. Videos are never previewed.

Images come from the internet, so a broken or oversized file just gives None
(Pillow refuses "decompression bomb" images on its own).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps

from igdl.downloader import IMAGE_SUFFIXES, SavedPost
from igdl.security import strip_control

# The copy kept in memory: big enough for a large panel, small enough to resize fast.
PREVIEW_MAX = 1080


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def newest_image(saved: SavedPost) -> Path | None:
    """The post's last new image (its last slide), or None if it saved only videos."""
    images = [f for f in saved.files if is_image(f)]
    return images[-1] if images else None


def caption_for_post(saved: SavedPost, path: Path) -> str:
    """'@natgeo · 2026-11-01 · DfN9Oosk9s2 · image 3 of 3'."""
    images = [f for f in saved.files if is_image(f)]
    text = f"@{saved.account} · {saved.date:%Y-%m-%d} · {saved.shortcode}"
    if len(images) > 1:
        text += f" · image {images.index(path) + 1} of {len(images)}"
    return strip_control(text)


def load_preview(path: Path, max_side: int = PREVIEW_MAX) -> Image.Image | None:
    """A copy of the image no larger than max_side, upright, or None if it can't be read.

    Slow for big photos: call it off the Tk thread.
    """
    try:
        with Image.open(path) as img:
            img.draft("RGB", (max_side, max_side))  # JPEG: decode at a smaller size, much faster
            img = ImageOps.exif_transpose(img)    # phone photos can be stored sideways
            img = img.convert("RGB")
            img.thumbnail((max_side, max_side))
            img.load()
            return img
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def fit(img: Image.Image, width: int, height: int) -> Image.Image:
    """The image scaled down to fit width x height, keeping its shape."""
    copy = img.copy()
    copy.thumbnail((max(1, width), max(1, height)))
    return copy
