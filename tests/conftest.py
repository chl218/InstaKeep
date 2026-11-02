"""Make every test headless: no window ever appears and nothing waits for a click.

Applied to all tests automatically:
  - tk.Tk() windows are withdrawn (hidden) as soon as they're created.
  - Message boxes and file dialogs don't open; their calls are recorded in
    the `dialogs` fixture and they answer "yes" / "no folder chosen".
  - InstaKeep's data, log and lock files point into the test's temp folder,
    so tests never touch the real data/, logs/ or downloads/.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox

import pytest

from instakeep import paths


class Dialogs:
    """Records every dialog a test triggered: (kind, message)."""

    def __init__(self) -> None:
        self.shown: list[tuple[str, str]] = []

    def texts(self, kind: str) -> list[str]:
        return [text for k, text in self.shown if k == kind]


@pytest.fixture(autouse=True)
def dialogs(monkeypatch) -> Dialogs:
    record = Dialogs()

    def fake(kind, answer=None):
        def show(title=None, message="", **_kw):
            record.shown.append((kind, message))
            return answer
        return show

    for kind in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(messagebox, kind, fake(kind))
    monkeypatch.setattr(messagebox, "askyesno", fake("askyesno", True))
    monkeypatch.setattr(filedialog, "askdirectory", fake("askdirectory", ""))
    return record


@pytest.fixture(autouse=True)
def hidden_windows(monkeypatch):
    real_init = tk.Tk.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        self.withdraw()  # never shown on screen

    monkeypatch.setattr(tk.Tk, "__init__", init)


@pytest.fixture(autouse=True)
def app_files_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(paths, "STORE_FILE", tmp_path / "data" / "instakeep.json")
    monkeypatch.setattr(paths, "LOCK_FILE", tmp_path / "data" / "run.lock")
    monkeypatch.setattr(paths, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(paths, "DEFAULT_OUTPUT", tmp_path / "downloads")
