"""preview.py: loading and captioning the newest downloaded image."""

from datetime import datetime
from pathlib import Path

from PIL import Image

from igdl.downloader import SavedPost
from instakeep import preview


def jpeg(path: Path, size=(400, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 30, 30)).save(path, "JPEG")
    return path


def post(tmp_path, *names):
    return SavedPost("natgeo", "DfN9Oosk9s2", datetime(2026, 11, 1, 23, 53),
                     [tmp_path / n for n in names])


def test_newest_image_is_the_last_slide_and_videos_are_skipped(tmp_path):
    carousel = post(tmp_path, "a_1.jpg", "a_2.mp4", "a_3.jpg")
    assert preview.newest_image(carousel) == tmp_path / "a_3.jpg"
    assert preview.newest_image(post(tmp_path, "v.mp4")) is None  # video only: no preview


def test_captions():
    carousel = post(Path("x"), "a_1.jpg", "a_2.jpg", "a_3.mp4")
    assert preview.caption_for_post(carousel, Path("x/a_2.jpg")) == \
        "@natgeo · 2026-11-01 · DfN9Oosk9s2 · image 2 of 2"
    single = post(Path("x"), "a.jpg")
    assert preview.caption_for_post(single, Path("x/a.jpg")) == "@natgeo · 2026-11-01 · DfN9Oosk9s2"


def test_load_shrinks_and_fit_keeps_the_shape(tmp_path):
    img = preview.load_preview(jpeg(tmp_path / "big.jpg", (3000, 1500)), max_side=1080)
    assert img is not None and max(img.size) <= 1080
    fitted = preview.fit(img, 300, 300)
    assert fitted.size == (300, 150)


def test_broken_file_gives_no_preview(tmp_path):
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")
    assert preview.load_preview(broken) is None
    assert preview.load_preview(tmp_path / "missing.jpg") is None


def test_captions_strip_control_characters():
    saved = SavedPost("nat\x1b[2Jgeo", "C1", datetime(2026, 11, 1), [Path("x/a.jpg")])
    assert "\x1b" not in preview.caption_for_post(saved, Path("x/a.jpg"))
