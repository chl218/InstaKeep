"""keep_awake(): sleep is held off during a download and allowed again after."""

import sys

import pytest

from instakeep import awake, runner


def test_windows_request_is_set_and_cleared(monkeypatch):
    calls = []
    monkeypatch.setattr(awake.sys, "platform", "win32")
    monkeypatch.setattr(awake, "_windows_set", lambda flags: calls.append(flags) or True)
    with awake.keep_awake() as ok:
        assert ok
        assert calls == [awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED]
    assert calls[-1] == awake.ES_CONTINUOUS  # sleep allowed again


def test_windows_request_is_cleared_after_an_error(monkeypatch):
    calls = []
    monkeypatch.setattr(awake.sys, "platform", "win32")
    monkeypatch.setattr(awake, "_windows_set", lambda flags: calls.append(flags) or True)
    with pytest.raises(RuntimeError):
        with awake.keep_awake():
            raise RuntimeError("download broke")
    assert calls[-1] == awake.ES_CONTINUOUS


def test_windows_failure_is_logged_and_the_download_goes_on(monkeypatch):
    logs = []
    monkeypatch.setattr(awake.sys, "platform", "win32")
    monkeypatch.setattr(awake, "_windows_set", lambda flags: False)
    with awake.keep_awake(log=logs.append) as ok:
        assert not ok
    assert "sleeping" in logs[0]


@pytest.mark.skipif(sys.platform != "win32", reason="the real Windows call")
def test_real_windows_call_succeeds():
    with awake.keep_awake() as ok:
        assert ok


def test_commands_for_macos_and_linux():
    found = lambda name: f"/usr/bin/{name}"  # noqa: E731 - stand-in for shutil.which
    assert awake.awake_command("darwin", 42, found) == ["caffeinate", "-i", "-w", "42"]
    linux = awake.awake_command("linux", 42, found)
    assert linux[0] == "systemd-inhibit" and "--what=sleep:idle" in linux
    assert awake.awake_command("linux", 42, lambda name: None) is None


def test_helper_process_is_stopped_afterwards(monkeypatch):
    class FakeProc:
        stopped = False

        def __init__(self, cmd, **kw):
            self.cmd = cmd
            FakeProc.last = self

        def terminate(self):
            FakeProc.stopped = True

        def wait(self, timeout):
            return 0

    monkeypatch.setattr(awake.sys, "platform", "darwin")
    monkeypatch.setattr(awake, "awake_command", lambda platform, pid: ["caffeinate", "-i"])
    monkeypatch.setattr(awake.subprocess, "Popen", FakeProc)
    with awake.keep_awake() as ok:
        assert ok and not FakeProc.stopped
    assert FakeProc.stopped


def test_no_helper_available_is_logged(monkeypatch):
    logs = []
    monkeypatch.setattr(awake.sys, "platform", "linux")
    monkeypatch.setattr(awake, "awake_command", lambda platform, pid: None)
    with awake.keep_awake(log=logs.append) as ok:
        assert not ok
    assert "power settings" in logs[0]


def test_downloads_keep_the_computer_awake(monkeypatch, tmp_path):
    from instakeep.store import Store

    used = []

    class Recorder:
        def __init__(self, log=None):
            used.append("on")

        def __enter__(self):
            return True

        def __exit__(self, *exc):
            used.append("off")

    monkeypatch.setattr(awake, "keep_awake", Recorder)
    store = Store(tmp_path / "s.json", tmp_path / "downloads")
    runner.run_headless(store)  # --run
    assert used == ["on", "off"]
