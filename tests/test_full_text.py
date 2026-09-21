"""Nothing is truncated on the way to Jev.

The cookbook's 60-character index was Hermes' default display width, not a limit of the
recipe; Claude Code shows the agent the whole description, so the cheap pass reads the whole
description too. These tests hold both widths open — a re-introduced cap would pass every
other test in the suite while quietly changing what the model is asked about.

The counterpart is the over-limit turn: the request can now exceed Jev's input budget, and
the contract for that is the existing fail-open — one logged row, exit 0, no suggestion.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import ScriptedClient, rerank_response, wide_response, write_skill

from scripts import roster as roster_mod
from scripts import route as route_mod
from scripts import router as router_mod
from scripts.jev_client import JevError

GOLDEN = Path(__file__).resolve().parent / "golden" / "inject-envelope.json"

PASSING_GATE = {
    "acts_on_user_system": 0.9,
    "would_follow_documented_procedure": 0.9,
    "prose_suffices": 0.1,
}
#: Longer than the 60 / 700 the 0.1.0 router cut at, so a cap of either size is visible.
LONG_DESCRIPTION = "Route a request to one skill. " + ("detail " * 60)
LONG_BODY = "# long-one\n" + ("body line with enough text to pass seven hundred chars. " * 60)
#: Any non-empty string routes: `skip_reason` only asks whether a key resolved at all.
#: Built rather than written out so a credential scanner has no literal to flag.
FAKE_CREDENTIAL = "x" * 12


@pytest.fixture
def env(skill_tree, tmp_path):
    return {
        "CLAUDE_CONFIG_DIR": str(skill_tree["root"] / "home" / ".claude"),
        "JEV_ROUTER_LOG": str(tmp_path / "decisions.jsonl"),
        "TYPESAFE_API_KEY": FAKE_CREDENTIAL,
        "HOME": str(skill_tree["root"] / "home"),
    }


def build(skill_tree, cwd=None):
    return roster_mod.build_roster(
        user_skills_dir=skill_tree["user"],
        plugins_manifest=skill_tree["installed"],
        settings_path=skill_tree["settings"],
        cwd=cwd if cwd is not None else skill_tree["project"],
    )


def test_roster_keeps_the_whole_description_and_the_whole_body(skill_tree):
    write_skill(skill_tree["user"], "long-one", description=LONG_DESCRIPTION, body=LONG_BODY)

    skill = next(s for s in build(skill_tree) if s.name == "long-one")

    assert len(LONG_DESCRIPTION) > 300 and len(LONG_BODY) > 2000  # the fixture is long enough
    assert skill.description == " ".join(LONG_DESCRIPTION.split())
    assert skill.body == LONG_BODY.strip()


def test_wide_request_asks_on_the_full_description(skill_tree):
    write_skill(skill_tree["user"], "long-one", description=LONG_DESCRIPTION, body=LONG_BODY)
    roster = build(skill_tree)
    client = ScriptedClient([wide_response({"long-one": 0.9}, PASSING_GATE)])

    router_mod.rank_wide(client, "route this request", roster)

    criteria = client.calls[0]["questions"]["which"]["criteria"]
    assert criteria["long-one"] == " ".join(LONG_DESCRIPTION.split())


def test_second_request_carries_the_full_body(skill_tree):
    write_skill(skill_tree["user"], "long-one", description=LONG_DESCRIPTION, body=LONG_BODY)
    candidates = [s for s in build(skill_tree) if s.name == "long-one"]
    client = ScriptedClient([rerank_response({"long-one": 0.9}, {"long-one": 0.8})])

    router_mod.rerank(client, "route this request", candidates)

    criterion = client.calls[0]["questions"]["which"]["criteria"]["long-one"]
    assert LONG_BODY.strip() in criterion
    assert " ".join(LONG_DESCRIPTION.split()) in criterion


def test_injected_envelope_is_unchanged_by_the_wider_input():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert router_mod.suggestion_block("tdd") == (golden["hookSpecificOutput"]["additionalContext"])


def test_over_limit_request_is_one_logged_row_and_no_suggestion(env, skill_tree, tmp_path):
    """A roster whose shortlist overflows Jev's input budget comes back 4xx.

    Nothing estimates the size before sending: the API is the authority on its own limit, and
    the router's answer to any failure is the same one it gives a timeout.
    """
    write_skill(skill_tree["user"], "long-one", description=LONG_DESCRIPTION, body=LONG_BODY)
    client = ScriptedClient(error=JevError("HTTP 400"))
    prompt = json.dumps(
        {
            "prompt": "route this request",
            "session_id": "sess-over-limit",
            "cwd": str(tmp_path),
            "hook_event_name": "UserPromptSubmit",
        }
    )

    stdout, record = route_mod.route(prompt, {**env, "JEV_ROUTER": "inject"}, client=client)
    wrote = route_mod.write_log(env, record)

    assert stdout == ""
    assert wrote is True
    assert record is not None
    assert record["suggestion"] is None
    assert record["reason"] == "error: JevError: HTTP 400"
    assert record["router_version"] == "0.2.0"


def test_project_skill_that_resolves_outside_its_skills_dir_is_left_out(skill_tree):
    """An untrusted repo controls ``.claude/skills``. A SKILL.md symlinked to a file elsewhere
    on the machine would otherwise be read whole and sent as that skill's body."""
    secret = skill_tree["root"] / "home" / "private-key"
    secret.write_text("---\nname: leak\ndescription: looks like a skill\n---\nPRIVATE BYTES\n")
    project_skills = skill_tree["project"] / ".claude" / "skills"
    (project_skills / "leak").mkdir()
    (project_skills / "leak" / "SKILL.md").symlink_to(secret)
    outside_dir = skill_tree["root"] / "elsewhere"
    write_skill(outside_dir, "linked-dir", description="a whole directory linked in")
    (project_skills / "linked-dir").symlink_to(outside_dir / "linked-dir")
    write_skill(project_skills, "honest", description="a regular project skill")

    names = {s.name for s in build(skill_tree, cwd=skill_tree["project"])}

    assert "honest" in names
    assert "leak" not in names
    assert "linked-dir" not in names


def test_project_skills_dir_that_is_itself_a_link_out_of_the_repo_is_left_out(skill_tree):
    """The containment root must come from the repo's own directory, not from wherever a
    symlinked ``.claude/skills`` points — otherwise the link moves the root with it."""
    elsewhere = skill_tree["root"] / "other-private-repo" / ".claude" / "skills"
    write_skill(elsewhere, "their-secret-skill", description="belongs to another repo")
    nested = skill_tree["project"] / "sub"
    (nested / ".claude").mkdir(parents=True)
    (nested / ".claude" / "skills").symlink_to(elsewhere)

    names = {s.name for s in build(skill_tree, cwd=nested)}

    assert "their-secret-skill" not in names
