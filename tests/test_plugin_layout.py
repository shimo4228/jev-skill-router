"""The plugin deployment: option env vars, the plugin data dir, and self-exclusion by path.

Claude Code hands an installed plugin its user config as ``CLAUDE_PLUGIN_OPTION_<KEY>`` and a
writable directory as ``CLAUDE_PLUGIN_DATA`` (primary source: plugins-reference.md, read
2026-09-21). The harness deployment keeps working off the bare ``JEV_ROUTER*`` names, so every
knob resolves the direct env var first — an unattended script must be able to set
``JEV_ROUTER=off`` for itself without editing the installed plugin's configuration.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import ScriptedClient, write_skill

from scripts import jev_client
from scripts import roster as roster_mod
from scripts import route as route_mod

ROUTE_PY = Path(__file__).resolve().parents[1] / "scripts" / "route.py"
ROUTER_ROOT = Path(__file__).resolve().parents[1]


def payload(prompt: str = "please run the tests", cwd: str = "/tmp/work") -> str:
    return json.dumps(
        {
            "prompt": prompt,
            "session_id": "sess-1",
            "cwd": cwd,
            "hook_event_name": "UserPromptSubmit",
        }
    )


@pytest.fixture
def base_env(skill_tree, tmp_path) -> dict[str, str]:
    """No key anywhere: every test here stops at the ``no-api-key`` skip unless it says
    otherwise, which keeps the whole file off the network by construction."""
    return {
        "CLAUDE_CONFIG_DIR": str(skill_tree["root"] / "home" / ".claude"),
        "HOME": str(skill_tree["root"] / "home"),
        "JEV_ROUTER_KEY_FILE": str(tmp_path / "no-such-key"),
    }


# --- mode ------------------------------------------------------------------------------


def test_mode_comes_from_the_plugin_option(base_env, tmp_path):
    """No ``JEV_ROUTER``: the installed plugin's configured mode is what runs."""
    env = {**base_env, "CLAUDE_PLUGIN_OPTION_MODE": "off", "JEV_ROUTER_LOG": str(tmp_path / "l")}

    assert route_mod.route(payload(), env) == ("", None)
    assert not (tmp_path / "l").exists()


def test_direct_env_outranks_the_plugin_option(base_env, tmp_path):
    """``JEV_ROUTER=off`` turns the router off for one process even when the plugin is
    configured to shadow — an unattended script cannot edit the plugin's config."""
    env = {
        **base_env,
        "JEV_ROUTER": "off",
        "CLAUDE_PLUGIN_OPTION_MODE": "shadow",
        "JEV_ROUTER_LOG": str(tmp_path / "l"),
    }

    assert route_mod.route(payload(), env) == ("", None)


def test_blank_direct_env_falls_through_to_the_plugin_option(base_env, tmp_path):
    env = {
        **base_env,
        "JEV_ROUTER": "   ",
        "CLAUDE_PLUGIN_OPTION_MODE": "off",
        "JEV_ROUTER_LOG": str(tmp_path / "l"),
    }

    assert route_mod.route(payload(), env) == ("", None)


def test_unknown_plugin_option_mode_skips_exactly_like_the_direct_env(base_env, tmp_path):
    """An unrecognised value must not fall through to the most expensive path, and must read
    the same in the log whichever env var carried it."""
    from_option = route_mod.route(
        payload(), {**base_env, "CLAUDE_PLUGIN_OPTION_MODE": "Shadow", "JEV_ROUTER_LOG": "x"}
    )[1]
    from_direct = route_mod.route(
        payload(), {**base_env, "JEV_ROUTER": "Shadow", "JEV_ROUTER_LOG": "x"}
    )[1]

    assert from_option is not None and from_direct is not None
    assert from_option["reason"] == "unknown-mode:Shadow"
    assert from_option["reason"] == from_direct["reason"]
    assert from_option["mode"] == from_direct["mode"] == "off"


def test_default_is_still_shadow_with_no_mode_anywhere(base_env):
    """Neither env var set: the record is written under ``shadow``, not ``inject``."""
    _, record = route_mod.route(payload(), base_env)

    assert record is not None and record["mode"] == "shadow"


# --- api key ---------------------------------------------------------------------------


def test_key_resolution_order(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("from-file\n", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".config" / "typesafe").mkdir(parents=True)
    (home / ".config" / "typesafe" / "api_key").write_text("from-home\n", encoding="utf-8")
    env = {
        "TYPESAFE_API_KEY": "direct",
        "CLAUDE_PLUGIN_OPTION_API_KEY": "from-option",
        "JEV_ROUTER_KEY_FILE": str(key_file),
        "HOME": str(home),
    }

    without_direct = {k: v for k, v in env.items() if k != "TYPESAFE_API_KEY"}

    assert jev_client.resolve_api_key(env) == "direct"
    assert jev_client.resolve_api_key(without_direct) == "from-option"
    assert jev_client.resolve_api_key({"JEV_ROUTER_KEY_FILE": str(key_file)}) == "from-file"
    assert jev_client.resolve_api_key({"HOME": str(home)}) == "from-home"


def test_blank_plugin_option_key_falls_through_to_the_key_file(tmp_path):
    key_file = tmp_path / "key"
    key_file.write_text("from-file\n", encoding="utf-8")

    key = jev_client.resolve_api_key(
        {"CLAUDE_PLUGIN_OPTION_API_KEY": "  ", "JEV_ROUTER_KEY_FILE": str(key_file)}
    )

    assert key == "from-file"


def test_plugin_option_key_never_reaches_the_log_or_stdout(base_env, skill_tree, tmp_path):
    """The invariant the direct env var already carries, pinned on the new path: the key is
    a credential, and the decision log is a file other tooling reads."""
    secret = "sk-plugin-option-secret-value"  # pragma: allowlist secret
    write_skill(skill_tree["user"], "tdd", description="Write the failing test first.")
    log = tmp_path / "decisions.jsonl"
    env = {
        **base_env,
        "CLAUDE_PLUGIN_OPTION_API_KEY": secret,
        "JEV_ROUTER": "shadow-child",
        "JEV_ROUTER_LOG": str(log),
        # Nothing listens here, so the client raises and the failure text lands in `reason`.
        "TYPESAFE_BASE_URL": "http://127.0.0.1:1",
    }

    stdout, record = route_mod.route(payload(), env)
    route_mod.write_log(env, record)

    assert stdout == ""
    assert record is not None and record["reason"].startswith("error:")
    assert secret not in json.dumps(record)
    assert secret not in log.read_text(encoding="utf-8")


def test_plugin_option_key_is_not_echoed_by_a_client_exception(tmp_path):
    secret = "sk-another-plugin-secret"  # pragma: allowlist secret
    client = jev_client.JevClient(secret, base_url="http://127.0.0.1:1")

    with pytest.raises(jev_client.JevError) as excinfo:
        client.ask(
            {"a": "1"},
            {"q": {"type": "choice", "options": ["x"]}},
            model="jev-1.13.0",
            timeout=0.5,
        )

    assert secret not in str(excinfo.value)


# --- log path --------------------------------------------------------------------------


def test_log_path_resolution_order(tmp_path):
    home = tmp_path / "home"
    data = tmp_path / "data"
    full = {
        "JEV_ROUTER_LOG": str(tmp_path / "direct.jsonl"),
        "CLAUDE_PLUGIN_OPTION_LOG_PATH": str(tmp_path / "option.jsonl"),
        "CLAUDE_PLUGIN_DATA": str(data),
        "HOME": str(home),
    }

    assert route_mod.log_path(full) == tmp_path / "direct.jsonl"
    assert route_mod.log_path({k: v for k, v in full.items() if k != "JEV_ROUTER_LOG"}) == (
        tmp_path / "option.jsonl"
    )
    assert route_mod.log_path({"CLAUDE_PLUGIN_DATA": str(data), "HOME": str(home)}) == (
        data / "decisions.jsonl"
    )
    assert route_mod.log_path({"HOME": str(home)}) == (
        home / ".claude" / "metrics" / "jev-decisions.jsonl"
    )


def test_plugin_data_dir_is_created_private(base_env, tmp_path):
    """``CLAUDE_PLUGIN_DATA`` may not exist yet. Rows are 0600, so the directory that holds
    them is 0700 — otherwise the mode on the file is the only thing standing there."""
    data = tmp_path / "plugin-data" / "nested"
    env = {**base_env, "CLAUDE_PLUGIN_DATA": str(data), "JEV_ROUTER": "shadow-child"}

    _, record = route_mod.route(payload(), env)

    assert route_mod.write_log(env, record) is True
    assert (data / "decisions.jsonl").exists()
    assert (data.stat().st_mode & 0o077) == 0


@pytest.mark.parametrize("key", ["CLAUDE_PLUGIN_OPTION_LOG_PATH", "CLAUDE_PLUGIN_DATA"])
def test_row_is_private_on_every_plugin_path(base_env, tmp_path, key):
    data = tmp_path / "d"
    data.mkdir()
    value = str(data / "decisions.jsonl") if key.endswith("LOG_PATH") else str(data)
    env = {**base_env, key: value, "JEV_ROUTER": "shadow-child"}

    _, record = route_mod.route(payload(), env)
    route_mod.write_log(env, record)

    written = route_mod.log_path(env)
    assert written is not None and (written.stat().st_mode & 0o077) == 0


@pytest.mark.parametrize("key", ["CLAUDE_PLUGIN_OPTION_LOG_PATH", "CLAUDE_PLUGIN_DATA"])
def test_symlinked_log_is_refused_on_every_plugin_path(base_env, tmp_path, key):
    """A planted link would otherwise make an unattended hook an append primitive against
    any file the user can write. The guard is the same whichever env var chose the path."""
    target = tmp_path / "victim"
    target.write_text("", encoding="utf-8")
    data = tmp_path / "d"
    data.mkdir()
    link = data / "decisions.jsonl"
    link.symlink_to(target)
    value = str(link) if key.endswith("LOG_PATH") else str(data)
    env = {**base_env, key: value, "JEV_ROUTER": "shadow-child"}

    _, record = route_mod.route(payload(), env)

    assert route_mod.write_log(env, record) is False
    assert target.read_text(encoding="utf-8") == ""


# --- self-exclusion by path ------------------------------------------------------------


def test_router_excludes_itself_in_the_harness_layout(tmp_path):
    """``<harness>/skills/jev-skill-router/`` — the name matches, and so does the path."""
    user = tmp_path / "skills"
    write_skill(user, "jev-skill-router", description="Routes prompts to skills.")
    write_skill(user, "tdd", description="Write the failing test first.")

    names = {
        s.name
        for s in roster_mod.build_roster(
            user_skills_dir=user, plugins_manifest=None, settings_path=None, cwd=None
        )
    }

    assert names == {"tdd"}


def test_router_excludes_itself_in_the_plugin_layout(tmp_path, monkeypatch):
    """Installed as a plugin the router is named ``jev-skill-router:jev-skill-router``, which
    the name-based exclusion misses entirely. The SKILL.md sits under the router's own root in
    both layouts, so the path is what settles it."""
    plugin_root = tmp_path / "plugins" / "jev-skill-router" / "0.1.0"
    (plugin_root / "scripts").mkdir(parents=True)
    write_skill(plugin_root / "skills", "jev-skill-router", description="Routes prompts.")
    user = tmp_path / "user-skills"
    write_skill(user, "tdd", description="Write the failing test first.")

    manifest = tmp_path / "installed_plugins.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "plugins": {
                    "jev-skill-router@jev-skill-router": [
                        {"scope": "user", "installPath": str(plugin_root)}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps({"enabledPlugins": {"jev-skill-router@jev-skill-router": True}}),
        encoding="utf-8",
    )

    # Name-based exclusion off, to prove the path alone carries it: as a plugin the roster
    # name is `jev-skill-router:jev-skill-router`, which never matches the bare SELF_NAME.
    def roster(**kwargs):
        return roster_mod.build_roster(
            user_skills_dir=user,
            plugins_manifest=manifest,
            settings_path=settings,
            cwd=None,
            **kwargs,
        )

    monkeypatch.setattr(roster_mod, "ROUTER_ROOT", tmp_path / "nowhere")
    assert {s.name for s in roster(exclude=())} == {"tdd", "jev-skill-router:jev-skill-router"}

    monkeypatch.setattr(roster_mod, "ROUTER_ROOT", plugin_root.resolve())
    assert {s.name for s in roster(exclude=())} == {"tdd"}


def test_a_skill_outside_the_router_root_is_kept(tmp_path, monkeypatch):
    """The path rule must not swallow anything that merely shares a name prefix."""
    elsewhere = tmp_path / "elsewhere"
    write_skill(elsewhere, "jev-skill-router-docs", description="Not the router.")
    monkeypatch.setattr(roster_mod, "ROUTER_ROOT", (tmp_path / "plugin").resolve())

    names = {
        s.name
        for s in roster_mod.build_roster(
            user_skills_dir=elsewhere, plugins_manifest=None, settings_path=None, cwd=None
        )
    }

    assert names == {"jev-skill-router-docs"}


def test_a_sibling_skill_in_the_same_plugin_survives(tmp_path, monkeypatch):
    """Self-exclusion is the router's own SKILL.md, not the whole install root. In the plugin
    layout the root holds every skill the plugin ships, so a root-wide rule would drop them."""
    plugin_root = tmp_path / "plugins" / "jev-skill-router" / "0.1.0"
    (plugin_root / "scripts").mkdir(parents=True)
    write_skill(plugin_root / "skills", "jev-skill-router", description="Routes prompts.")
    write_skill(plugin_root / "skills", "jev-report", description="Reads the decision log.")
    monkeypatch.setattr(roster_mod, "ROUTER_ROOT", plugin_root.resolve())

    names = {
        s.name
        for s in roster_mod.build_roster(
            user_skills_dir=plugin_root / "skills",
            plugins_manifest=None,
            settings_path=None,
            cwd=None,
            exclude=(),
        )
    }

    assert names == {"jev-report"}


def test_router_root_points_at_the_package_parent():
    """Both deployments put ``scripts/`` one level under the root, so one expression covers
    the harness (``skills/jev-skill-router/``) and the plugin (``<install>/``)."""
    assert roster_mod.ROUTER_ROOT == ROUTER_ROOT.resolve()
    assert (roster_mod.ROUTER_ROOT / "scripts" / "roster.py").is_file()


# --- skip-cwd prefixes -----------------------------------------------------------------


def test_skip_cwd_prefix_is_configured_not_baked_in(base_env, tmp_path):
    """The skill-comply sandbox is a fact about one harness, not about the published hook, so
    with nothing configured its cwd is an ordinary session."""
    env = {**base_env, "JEV_ROUTER": "shadow-child", "TYPESAFE_API_KEY": "k"}
    sandbox = "/tmp/skill-comply-sandbox/s1"

    assert route_mod.skip_cwd_prefixes(env) == ()
    # Not skipped, so it runs on into the client seam — an empty stub, which fails open.
    ran = route_mod.route(payload(cwd=sandbox), env, client=ScriptedClient([]))[1]
    assert ran is not None and ran["reason"] != "sandbox"

    configured = {**env, "JEV_ROUTER_SKIP_CWD_PREFIX": "/tmp/skill-comply-sandbox:/tmp/other/"}
    for cwd in ("/tmp/skill-comply-sandbox", sandbox, "/tmp/other/x"):
        record = route_mod.route(payload(cwd=cwd), configured)[1]
        assert record is not None and record["reason"] == "sandbox"


def test_skip_cwd_prefix_still_normalises_the_private_alias(base_env):
    """macOS resolves /tmp through /private, and a hook payload can carry either spelling."""
    prefixes = route_mod.skip_cwd_prefixes(
        {"JEV_ROUTER_SKIP_CWD_PREFIX": "/tmp/skill-comply-sandbox"}
    )

    assert route_mod.in_sandbox("/private/tmp/skill-comply-sandbox/s1", prefixes) is True
    assert route_mod.in_sandbox("/tmp/skill-comply-sandbox", prefixes) is True


def test_skip_cwd_prefix_does_not_match_a_sibling_directory():
    prefixes = route_mod.skip_cwd_prefixes({"JEV_ROUTER_SKIP_CWD_PREFIX": "/tmp/sandbox"})

    assert route_mod.in_sandbox("/tmp/sandbox-other/x", prefixes) is False


def test_empty_entries_in_the_prefix_list_match_nothing():
    """A stray colon must not become a prefix that swallows every prompt."""
    assert route_mod.skip_cwd_prefixes({"JEV_ROUTER_SKIP_CWD_PREFIX": ": : ::"}) == ()
    assert route_mod.in_sandbox("/tmp/work", ()) is False


# --- the shadow child ------------------------------------------------------------------


def test_shadow_child_inherits_the_plugin_env(base_env, skill_tree, tmp_path):
    """The detached half re-execs this file, so every knob the parent resolved has to reach
    it — the child re-reads them all from its own environment."""
    write_skill(skill_tree["user"], "tdd", description="Write the failing test first.")
    data = tmp_path / "plugin-data"
    env = {
        **base_env,
        "CLAUDE_PLUGIN_OPTION_MODE": "shadow",
        "CLAUDE_PLUGIN_OPTION_API_KEY": "test-key",
        "CLAUDE_PLUGIN_DATA": str(data),
        "CLAUDE_PLUGIN_ROOT": str(ROUTER_ROOT),
        "TYPESAFE_BASE_URL": "http://127.0.0.1:1",
        "PATH": "/usr/bin:/bin",
    }
    del env["JEV_ROUTER_KEY_FILE"]

    result = subprocess.run(
        [sys.executable, str(ROUTE_PY)],
        input=payload(),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    log = data / "decisions.jsonl"
    for _ in range(100):
        if log.exists() and log.read_text(encoding="utf-8").strip():
            break
        time.sleep(0.05)
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]
    # The child got the key (no `no-api-key` skip) and the log path, and stayed in shadow.
    assert len(rows) == 1
    assert rows[0]["mode"] == "shadow"
    assert rows[0]["reason"].startswith("error:")
    assert "test-key" not in log.read_text(encoding="utf-8")


def test_plugin_layout_smoke_writes_a_skip_row(base_env, tmp_path):
    """The acceptance smoke, as a test: no key anywhere, exit 0, empty stdout, one skip row
    in the plugin's data dir."""
    data = tmp_path / "plugin-data"
    env = {
        **base_env,
        "CLAUDE_PLUGIN_ROOT": str(ROUTER_ROOT),
        "CLAUDE_PLUGIN_DATA": str(data),
        "CLAUDE_PLUGIN_OPTION_MODE": "shadow",
        "JEV_ROUTER_KEY_FILE": "/nonexistent",
        "PATH": "/usr/bin:/bin",
    }

    result = subprocess.run(
        [sys.executable, str(ROUTE_PY)],
        input=json.dumps(
            {
                "prompt": "hello",
                "session_id": "s",
                "cwd": "/tmp",
                "hook_event_name": "UserPromptSubmit",
            }
        ),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    rows = [
        json.loads(line)
        for line in (data / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(rows) == 1 and rows[0]["reason"] == "no-api-key"
