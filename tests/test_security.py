import io
import sys

import pytest

from igdl import downloader, security


@pytest.mark.parametrize("name,ok", [
    ("natgeo", True), ("a.b_c9", True), ("../etc", False),
    ("a/b", False), ("a\\b", False), ("", False), ("x" * 31, False),
])
def test_is_valid_username(name, ok):
    assert security.is_valid_username(name) is ok


def test_strip_control_keeps_text_and_newlines():
    assert security.strip_control("a\x1b[2Jb\x07\tc\nd") == "a[2Jb\tc\nd"


def test_logging_strips_terminal_escapes(tmp_path, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    loader = downloader.build_loader(tmp_path)
    loader.context.log("[caption \x1b]0;pwned\x07 \x1b[2J]")
    assert "\x1b" not in out.getvalue() and "\x07" not in out.getvalue()
    assert "caption" in out.getvalue()


def test_strip_control_removes_bidi_overrides():
    # U+202E (right-to-left override) would display "txt.exe" as "exe.txt".
    assert security.strip_control("a‮txt.exe⁦b⁩") == "atxt.exeb"


def test_normalize_username():
    assert security.normalize_username("  @NatGeo ") == "natgeo"
    with pytest.raises(ValueError):
        security.normalize_username("../etc")


def test_describe_unexpected_has_summary_and_traceback():
    try:
        raise OSError("disk \x1b[2Jfull")
    except OSError as e:
        text = security.describe_unexpected(e)
    first, _, rest = text.partition("\n")
    assert first == "unexpected error (OSError): disk [2Jfull"  # control chars stripped
    assert "Traceback (most recent call last)" in rest and "\x1b" not in rest
