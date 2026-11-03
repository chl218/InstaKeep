"""Make the README screenshots of the window's two tabs (Windows only).

The window shows stub data: made-up usernames, a made-up post link and sample log
lines. Nothing is downloaded and the real data/ and downloads/ folders aren't
touched (the store lives in a temporary folder). The window is placed off-screen
and captured with PrintWindow, so it never appears on the desktop.

    .venv\\Scripts\\python docs\\make_screenshots.py

Writes docs/screenshot-batch.png and docs/screenshot-individual.png.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import tempfile
import tkinter as tk
import zlib
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS.parent / "src"))

from instakeep import gui  # noqa: E402 - needs the sys.path line above
from instakeep.store import Store  # noqa: E402

# Placeholder accounts: (username, status, images, seconds, run day). Not real users.
STUB_USERS = [
    ("example.user", "ok, 3 new", 48, 95, 1),
    ("sample_account", "ok, 0 new", 120, 210, 1),
    ("demo_profile", "ok, 5 new", 22, 61, 2),
]
NEW_USER = "just_added"  # in the list but never downloaded: left out of the estimate
STUB_LINK = "https://www.instagram.com/p/EXAMPLE_POST/"
STUB_OUTPUT = r"D:\Pictures\InstaKeep"


def stub_store(folder: Path) -> Store:
    """A store in `folder` with the placeholder users and some history."""
    store = Store(folder / "instakeep.json", Path(STUB_OUTPUT))
    for name, status, images, seconds, day in STUB_USERS:
        store.add_user(name)
        store.record_result(name, status, when=datetime(2026, 11, day, 8, 0), run_stats={
            "runs": 2, "seconds": seconds, "posts": 10, "new_posts": 4, "images": images,
            "image_seconds": seconds * 0.8, "queries": 6, "media_count": 150,
            "last_seconds": seconds / 2, "last_images": images // 4,
            "longest_seconds": seconds * 0.6,
        })
    store.add_user(NEW_USER)
    return store


def capture(root: tk.Tk, out: Path) -> None:
    """Save the window (title bar included, no shadow) as a PNG via PrintWindow."""
    root.update()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = user32.GetAncestor(root.winfo_id(), 2)  # GA_ROOT: the real top-level window
    win, frame = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(win))
    # The visible frame, without the invisible resize borders around it.
    ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(frame), ctypes.sizeof(frame))
    full_w, full_h = win.right - win.left, win.bottom - win.top

    screen = user32.GetDC(0)
    dc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, full_w, full_h)
    gdi32.SelectObject(dc, bmp)
    user32.PrintWindow(hwnd, dc, 2)  # PW_RENDERFULLCONTENT: works off-screen
    header = struct.pack("<IiiHHIIiiII", 40, full_w, -full_h, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(full_w * full_h * 4)
    gdi32.GetDIBits(dc, bmp, 0, full_h, pixels, ctypes.c_char_p(header), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(dc)
    user32.ReleaseDC(0, screen)

    left, top = frame.left - win.left, frame.top - win.top
    w, h = frame.right - frame.left, frame.bottom - frame.top
    raw = bytearray()
    for y in range(top, top + h):
        row = pixels.raw[(y * full_w + left) * 4:(y * full_w + left + w) * 4]
        rgb = bytearray(w * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]  # BGRA -> RGB
        raw += b"\x00" + rgb
    write_png(out, w, h, bytes(raw))


def write_png(path: Path, width: int, height: int, rows: bytes) -> None:
    """Minimal PNG writer (8-bit RGB), so no imaging library is needed."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def main() -> int:
    if sys.platform != "win32":
        print("This script uses Windows' PrintWindow; run it on Windows.")
        return 1
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text, as the real window
    with tempfile.TemporaryDirectory() as tmp:
        root = tk.Tk()
        # Fully transparent and off the taskbar, so nothing shows on the desktop. It has
        # to stay on-screen: Windows doesn't paint windows that are entirely off-screen.
        root.attributes("-alpha", 0.0)
        root.attributes("-toolwindow", True)
        app = gui.App(root, stub_store(Path(tmp)))
        root.attributes("-toolwindow", False)  # restore the normal title bar for the picture
        root.geometry("+0+0")

        def batch() -> None:
            app.tree.selection_set(["example.user"])
            for line in ("=== [1/3] @example.user (newest 5) ===",
                         "Downloading 5 image post(s) from @example.user",
                         "[1/5] 2026-11-01 EXAMPLE_POST",
                         "    tags: #sample; #placeholder",
                         "@example.user: 3 new file(s) (3 image(s), 0 video(s)) in 41 s"):
                app._append_log(line)
            app.status.set("Done. 3/3 user(s) OK, 8 new file(s).")

        def individual() -> None:
            app.tabs.select(1)
            app._clear_log()
            app.post_link.set(STUB_LINK)
            app.add_owner.set(True)
            for line in ("Downloading EXAMPLE_POST (2026-11-01) from @example.user",
                         "    tags: #sample; #placeholder",
                         "@example.user is already in the saved list.",
                         "Done. 3 new file(s) from @example.user."):
                app._append_log(line)
            app.status.set("Done. 3 new file(s) from @example.user.")

        # One step at a time, each scheduled by the one before, with time for Tk to
        # paint before each capture (PrintWindow copies what has been drawn).
        steps = [batch, lambda: capture(root, DOCS / "screenshot-batch.png"),
                 individual, lambda: capture(root, DOCS / "screenshot-individual.png"),
                 root.destroy]

        def run_next() -> None:
            steps.pop(0)()
            if steps:
                root.after(800, run_next)

        root.after(300, run_next)
        root.mainloop()
    print("Wrote docs/screenshot-batch.png and docs/screenshot-individual.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
