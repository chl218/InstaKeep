"""Project rules CLAUDE.md states but code doesn't otherwise check."""

import re
import subprocess
import sys
from pathlib import Path

import igdl
import instakeep

ROOT = Path(__file__).resolve().parents[1]


def pyproject_version():
    # A regex, not tomllib: tomllib is 3.11+ and we still support 3.10.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    return re.search(r'^version\s*=\s*"([^"]+)"', project, re.MULTILINE).group(1)


def test_versions_match():
    assert igdl.__version__ == instakeep.__version__ == pyproject_version()


# Runs in a fresh interpreter (-I: no site-packages, no PYTHONPATH), the way
# instakeep.py starts before setup has checked the dependencies.
PRE_SETUP_IMPORTS = r"""
import sys
sys.path.insert(0, sys.argv[1])
import igdl.security, instakeep, instakeep.bootstrap, instakeep.paths

ours = {"igdl", "igdl.security", "instakeep", "instakeep.bootstrap", "instakeep.paths"}
bad = sorted(
    name for name in sys.modules
    if name.split(".")[0] not in sys.stdlib_module_names and name not in ours
    and name != "__main__"
)
print("\n".join(bad))
"""


def test_pre_setup_modules_are_stdlib_only():
    result = subprocess.run(
        [sys.executable, "-I", "-c", PRE_SETUP_IMPORTS, str(ROOT / "src")],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", "imported before setup: " + result.stdout
