import os
from datetime import datetime
from types import SimpleNamespace

import piexif
import pytest

from igdl import downloader, tags

# Smallest file piexif accepts as a JPEG: start marker, JFIF header, scan, end marker.
# (piexif only reads the segment layout, not the image data.)
TINY_JPEG = bytes.fromhex(
    "ffd8"
    "ffe000104a46494600010100000100010000"
    "ffda000801010000003f00" "00"
    "ffd9"
)


def make_jpeg(path):
    path.write_bytes(TINY_JPEG)
    return path


@pytest.mark.parametrize("caption,expected", [
    ("Wow this #portrait is awesome.", ["#portrait"]),
    ("#a #b, #c! #a", ["#a", "#b", "#c"]),               # punctuation ends a tag; no duplicates
    ("#Portrait then #portrait", ["#Portrait"]),          # duplicates ignore case; first kept
    ("#a#b", ["#a", "#b"]),
    ("snake #case_tag2 and #日本", ["#case_tag2", "#日本"]),  # any language
    ("no tags here", []),
    ("a lone # sign", []),
    ("", []),
    (None, []),
])
def test_extract_hashtags(caption, expected):
    assert tags.extract_hashtags(caption) == expected


def test_write_and_read_tags_round_trip(tmp_path):
    img = make_jpeg(tmp_path / "a.jpg")
    assert tags.read_tags(img) == []
    assert tags.write_tags(img, ["#portrait", "#日本"]) is True
    assert tags.read_tags(img) == ["#portrait", "#日本"]
    # Stored where Windows reads Tags: EXIF XPKeywords, UTF-16LE, ";"-separated.
    raw = bytes(piexif.load(str(img))["0th"][piexif.ImageIFD.XPKeywords])
    assert raw == "#portrait;#日本\x00".encode("utf-16-le")


def test_write_tags_skips_unchanged_and_keeps_file_date(tmp_path):
    img = make_jpeg(tmp_path / "a.jpg")
    post_date = datetime(2022, 5, 31, 12, 0).timestamp()
    os.utime(img, (post_date, post_date))
    assert tags.write_tags(img, ["#x"]) is True
    assert os.path.getmtime(img) == pytest.approx(post_date)  # still the post's date
    assert tags.write_tags(img, ["#x"]) is False               # already tagged: untouched
    assert tags.write_tags(img, []) is False                   # nothing to write


def test_tag_post_images_single_and_carousel(tmp_path):
    single = make_jpeg(tmp_path / "u_2026_A.jpg")
    slides = [make_jpeg(tmp_path / f"u_2026_B_{i}.jpg") for i in (1, 2, 10)]
    other = make_jpeg(tmp_path / "u_2026_C_1.jpg")
    (tmp_path / "u_2026_B.txt").write_text("caption file is not an image")

    assert tags.tag_post_images(tmp_path, "u_2026_A", ["#one"]) == 1
    assert tags.tag_post_images(tmp_path, "u_2026_B", ["#two"]) == 3
    assert tags.read_tags(single) == ["#one"]
    assert all(tags.read_tags(s) == ["#two"] for s in slides)
    assert tags.read_tags(other) == []  # another post's file is left alone


def _download_one(tmp_path, monkeypatch, tags_option, caption_text, caption_option=False):
    """Run download_user on a one-post fake feed; download_post writes a real JPEG."""
    post = SimpleNamespace(shortcode="SC1", date_utc=datetime(2026, 1, 2, 3, 4, 5),
                           is_video=False, caption=caption_text)
    profile = SimpleNamespace(username="u", is_private=False, mediacount=1,
                              get_posts=lambda: iter([post]))
    monkeypatch.setattr(downloader.instaloader.Profile, "from_username", lambda ctx, name: profile)
    loader = downloader.build_loader(tmp_path, caption=caption_option, quiet=True)
    monkeypatch.setattr(loader, "format_filename", lambda p, target: f"{target}_{p.shortcode}")

    def fake_download_post(p, target):
        (tmp_path / target).mkdir(exist_ok=True)
        make_jpeg(tmp_path / target / f"{target}_{p.shortcode}.jpg")

    monkeypatch.setattr(loader, "download_post", fake_download_post)
    logs = []
    downloader.download_user(loader, "u", log=logs.append, tags=tags_option)
    return tmp_path / "u" / "u_SC1.jpg", logs


def test_download_writes_hashtags_when_tags_on(tmp_path, monkeypatch):
    # Tags don't need the caption .txt option.
    img, logs = _download_one(tmp_path, monkeypatch, True, "Wow this #portrait is awesome #sky")
    assert tags.read_tags(img) == ["#portrait", "#sky"]
    assert "    tags: #portrait; #sky" in logs


def test_download_leaves_tags_alone_when_tags_off(tmp_path, monkeypatch):
    # Caption .txt on, Tags off: the image is not tagged.
    img, _ = _download_one(tmp_path, monkeypatch, False, "Wow this #portrait is awesome",
                           caption_option=True)
    assert tags.read_tags(img) == []


def test_tag_post_images_skips_a_broken_jpeg(tmp_path):
    (tmp_path / "u_A_1.jpg").write_bytes(b"\xff\xd8 not really a jpeg")
    good = make_jpeg(tmp_path / "u_A_2.jpg")
    assert tags.tag_post_images(tmp_path, "u_A", ["#x"]) == 1  # the broken one is left alone
    assert tags.read_tags(good) == ["#x"]
