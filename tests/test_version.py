"""The version is semver, and lives in one place."""

import re
import subprocess
import sys
from pathlib import Path

from os_e_man import __version__

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
ROOT = Path(__file__).parent.parent


def test_version_is_semver():
    assert SEMVER.match(__version__), __version__


def test_pyproject_reads_it_from_the_package():
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in py and 'attr = "os_e_man.__version__"' in py
    assert not re.search(r'^version\s*=\s*"', py, re.M)


def test_changelog_has_this_version():
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_cli_prints_it():
    out = subprocess.run([sys.executable, "-m", "os_e_man", "--version"], cwd=ROOT,
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == f"os_e_man {__version__}"
