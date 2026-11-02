"""igdl - download a public Instagram profile's posts.

Modules:
  cli.py         command-line parsing, error -> exit code mapping
  downloader.py  instaloader setup, rate-limit pauses, the download loop
  tags.py        caption #hashtags -> the images' Tags (EXIF XPKeywords)
  security.py    pure helpers for untrusted input and text

See README.md for usage and the architecture diagrams.
"""

__version__ = "0.1.0"  # shown by `igdl --version`; keep in sync with pyproject.toml
