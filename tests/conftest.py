"""Shared fixtures: a fake Jev client and a skill-tree builder.

No test touches the network. The client is a scripted stub whose `ask` pops the next
canned response, so a test that expects "the second call never happens" fails loudly
(an unconsumed response) instead of silently passing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class ScriptedClient:
    """Stands in for scripts.jev_client.JevClient.

    Records every payload it was handed and returns the queued responses in order.
    """

    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict] = []

    def ask(self, state, questions, *, model=None, timeout=None):
        self.calls.append(
            {"state": state, "questions": questions, "model": model, "timeout": timeout}
        )
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("ScriptedClient.ask called more times than scripted")
        return self.responses.pop(0)


def choice_answer(probabilities: dict[str, float]) -> dict:
    winner = max(probabilities.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return {"type": "choice", "choice": winner, "probabilities": dict(probabilities)}


def wide_response(probabilities: dict[str, float], gate: dict[str, float]) -> dict:
    answers: dict[str, dict] = {"which": choice_answer(probabilities)}
    for key, value in gate.items():
        answers[f"gate::{key}"] = {"type": "noul", "noul": value}
    return {"model": "jev-1.13.0", "answers": answers, "usage": {}}


def rerank_response(probabilities: dict[str, float], fits: dict[str, float]) -> dict:
    answers: dict[str, dict] = {"which": choice_answer(probabilities)}
    for name, value in fits.items():
        answers[f"fits::{name}"] = {"type": "noul", "noul": value}
    return {"model": "jev-1.13.0", "answers": answers, "usage": {}}


def write_skill(
    directory: Path, name: str, *, description: str = "", body: str = "", extra: str = ""
) -> Path:
    """Create <directory>/<name>/SKILL.md with a minimal frontmatter."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    front = [f"name: {name}", f"description: {description or f'What {name} does.'}"]
    if extra:
        front.append(extra)
    (skill_dir / "SKILL.md").write_text(
        "---\n" + "\n".join(front) + "\n---\n\n" + (body or f"# {name}\n"),
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def skill_tree(tmp_path: Path):
    """A user dir, a plugins dir with two plugins, and a project dir."""
    user = tmp_path / "home" / ".claude" / "skills"
    user.mkdir(parents=True)
    plugins_root = tmp_path / "home" / ".claude" / "plugins" / "cache"
    project = tmp_path / "work" / "repo"
    (project / ".git").mkdir(parents=True)
    (project / ".claude" / "skills").mkdir(parents=True)

    on = plugins_root / "on-market" / "alpha" / "1.0.0"
    off = plugins_root / "off-market" / "beta" / "1.0.0"
    write_skill(on / "skills", "alpha-skill")
    write_skill(off / "skills", "beta-skill")

    installed = tmp_path / "home" / ".claude" / "plugins" / "installed_plugins.json"
    installed.parent.mkdir(parents=True, exist_ok=True)
    installed.write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": {
                    "alpha@on-market": [{"scope": "user", "installPath": str(on)}],
                    "beta@off-market": [{"scope": "user", "installPath": str(off)}],
                },
            }
        ),
        encoding="utf-8",
    )
    settings = tmp_path / "home" / ".claude" / "settings.json"
    settings.write_text(
        json.dumps({"enabledPlugins": {"alpha@on-market": True, "beta@off-market": False}}),
        encoding="utf-8",
    )

    return {
        "root": tmp_path,
        "user": user,
        "project": project,
        "installed": installed,
        "settings": settings,
    }
