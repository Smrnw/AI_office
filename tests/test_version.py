"""Версия записана в одном месте и везде одинаковая."""
import re
from pathlib import Path

from pixel_office import __version__

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_version_reported_by_api(client):
    assert client.get("/api/health").json()["version"] == __version__
    assert client.get("/api/state").json()["version"] == __version__


def test_version_has_changelog_entry():
    assert f"## [{__version__}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_pyproject_takes_version_from_package():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text and 'attr = "pixel_office.__version__"' in text
    assert not re.search(r'^version\s*=\s*"', text, re.M)
