"""One version, four places: pyproject, the plugin manifest, the decision log's
``router_version`` and the User-Agent every request carries. A stale User-Agent went out
on every 0.2.0 request before this test existed."""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts import jev_client, router

ROOT = Path(__file__).resolve().parent.parent


def test_every_version_declaration_agrees() -> None:
    # Python 3.10 is supported and has no tomllib; the [project] version is the first one.
    match = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert match is not None
    pyproject = match.group(1)
    manifest = ROOT / ".claude-plugin" / "plugin.json"
    if manifest.is_file():  # the harness copy of this skill ships without the plugin manifest
        assert json.loads(manifest.read_text())["version"] == pyproject
    assert router.ROUTER_VERSION == pyproject
    assert jev_client.USER_AGENT == f"jev-skill-router/{pyproject}"
