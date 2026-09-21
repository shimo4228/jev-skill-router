#!/usr/bin/env python3
"""UserPromptSubmit hook entrypoint. Reads the payload on stdin, exits 0 whatever happens.

Modes (``JEV_ROUTER``, else ``CLAUDE_PLUGIN_OPTION_MODE``, default ``shadow``):

  off          nothing runs and nothing is written
  shadow       re-exec this file detached, hand it the same payload, exit immediately — the
               prompt is never made to wait on an API call while the recipe is unproven
  inject       run in-line under a wall-clock budget and, only if there is a suggestion,
               print the ``additionalContext`` envelope
  shadow-child the detached half of ``shadow``; logs, prints nothing

Fail-open is the whole contract. Any exception anywhere reaches ``main`` and becomes exit 0
with an empty stdout, because a routing hook that can block a prompt is worse than one that
sometimes says nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import decision_log  # noqa: E402
from scripts import roster as roster_mod
from scripts import router as router_mod
from scripts.jev_client import JevClient, resolve_api_key  # noqa: E402

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_SHADOW_CHILD = "shadow-child"
MODE_INJECT = "inject"
DEFAULT_MODE = MODE_SHADOW
MODES = (MODE_OFF, MODE_SHADOW, MODE_SHADOW_CHILD, MODE_INJECT)

#: Longer prompts are pasted material — a log, a diff, a whole file. What such a prompt needs
#: is read out of the pasted text, not out of a roster, and the request is the one part of a
#: Jev call that is charged twice: ``state`` rides along with every chunk of a split roster.
MAX_PROMPT_CHARS = 4000
#: Wall clock for the whole inject path. A prompt waits for this; nothing else is worth it.
INJECT_BUDGET_S = 3.0
#: The detached shadow half has no human waiting on it.
SHADOW_BUDGET_S = 30.0
DEFAULT_LOG_RELATIVE = ".claude/metrics/jev-decisions.jsonl"
#: Filename used inside ``CLAUDE_PLUGIN_DATA`` when the plugin names no log path.
PLUGIN_LOG_NAME = "decisions.jsonl"


def resolve_mode(env: Mapping[str, str]) -> str:
    """``JEV_ROUTER`` -> ``CLAUDE_PLUGIN_OPTION_MODE`` -> ``shadow``.

    The direct variable stays on top so one unattended script can set ``JEV_ROUTER=off`` for
    itself without editing the configuration of an installed plugin — and so ``_spawn_shadow``
    can hand its child ``shadow-child`` whatever the plugin is configured with.
    """
    for name in ("JEV_ROUTER", "CLAUDE_PLUGIN_OPTION_MODE"):
        value = (env.get(name) or "").strip()
        if value:
            return value
    return DEFAULT_MODE


def log_path(env: Mapping[str, str]) -> Path | None:
    """``JEV_ROUTER_LOG`` -> ``CLAUDE_PLUGIN_OPTION_LOG_PATH`` -> ``$CLAUDE_PLUGIN_DATA`` ->
    ``~/.claude/metrics/``. An installed plugin gets a writable directory of its own, which is
    where its rows belong: the harness path is a fact about one machine's layout."""
    for name in ("JEV_ROUTER_LOG", "CLAUDE_PLUGIN_OPTION_LOG_PATH"):
        override = (env.get(name) or "").strip()
        if override:
            return Path(override)
    data_dir = (env.get("CLAUDE_PLUGIN_DATA") or "").strip()
    if data_dir:
        return Path(data_dir) / PLUGIN_LOG_NAME
    home = env.get("HOME")
    return Path(home) / DEFAULT_LOG_RELATIVE if home else None


def skip_cwd_prefixes(env: Mapping[str, str]) -> tuple[str, ...]:
    """Colon-separated directories whose sessions are not real usage, empty by default.

    The harness needs ``/tmp/skill-comply-sandbox`` skipped because skill-comply runs
    synthetic sessions there whose prompts are fixtures. That is a fact about one harness, not
    about a hook other people install, so it is configuration rather than a baked-in constant.
    """
    raw = env.get("JEV_ROUTER_SKIP_CWD_PREFIX") or ""
    return tuple(part for part in (p.strip().rstrip("/") for p in raw.split(":")) if part)


def config_dir(env: Mapping[str, str]) -> Path | None:
    override = env.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override)
    home = env.get("HOME")
    return Path(home) / ".claude" if home else None


def in_sandbox(cwd: str, prefixes: Sequence[str] = ()) -> bool:
    """macOS resolves /tmp through /private, so strip that prefix once and match one shape."""
    stripped = cwd[len("/private") :] if cwd.startswith("/private") else cwd
    return any(stripped == p or stripped.startswith(p + "/") for p in prefixes)


def skip_reason(prompt: str, cwd: str, api_key: str, prefixes: Sequence[str] = ()) -> str | None:
    """Why this turn is not worth an API call, or None to proceed."""
    if not prompt.strip():
        return "empty-prompt"
    if prompt.startswith("/"):
        return "slash-command"
    if len(prompt) > MAX_PROMPT_CHARS:
        return "prompt-too-long"
    if not api_key:
        return "no-api-key"
    if in_sandbox(cwd, prefixes):
        return "sandbox"
    return None


def _spawn_shadow(raw_stdin: str) -> None:
    """Re-exec this file in its own session and walk away.

    ``start_new_session=True`` detaches the child from the hook's process group, so Claude
    Code moving on does not take the measurement with it.
    """
    env = dict(os.environ)
    env["JEV_ROUTER"] = MODE_SHADOW_CHILD
    process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(Path(__file__).resolve())],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    if process.stdin is not None:
        try:
            process.stdin.write(raw_stdin.encode("utf-8"))
        finally:
            process.stdin.close()


def _skip_record(payload: Mapping[str, Any], mode: str, reason: str) -> dict[str, Any]:
    return decision_log.build_record(
        project=str(payload.get("cwd") or ""),
        session=str(payload.get("session_id") or ""),
        mode=mode,
        model=router_mod.MODEL,
        router_version=router_mod.ROUTER_VERSION,
        question_hash=router_mod.QUESTION_HASH,
        roster_hash="",
        n_skills=0,
        n_by_source={"user": 0, "plugin": 0, "project": 0},
        prompt=str(payload.get("prompt") or ""),
        elapsed_ms=0,
        reason=reason,
    )


def route(
    raw_stdin: str,
    env: Mapping[str, str],
    *,
    client: router_mod.Client | None = None,
    spawn: Callable[[str], None] = _spawn_shadow,
) -> tuple[str, dict[str, Any] | None]:
    """Decide what this turn gets. Returns ``(stdout_text, log_record_or_None)``.

    Pure with respect to the filesystem except for reading the roster — ``write_log`` does
    the appending, so a caller (and every test) can inspect the row before it lands.
    """
    mode = resolve_mode(env)
    if mode == MODE_OFF:
        return "", None
    try:
        payload = json.loads(raw_stdin)
    except ValueError:
        return "", None
    if not isinstance(payload, dict):
        return "", None

    # An unrecognised value is a typo, not a request to run the most expensive path. Falling
    # through to `_run` would make `JEV_ROUTER=OFF` block every prompt for up to 30 seconds
    # and keep sending prompts out — the opposite of what whoever typed it meant.
    if mode not in MODES:
        return "", _skip_record(payload, MODE_OFF, f"unknown-mode:{mode[:32]}")

    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or "")
    reason = skip_reason(prompt, cwd, resolve_api_key(env), skip_cwd_prefixes(env))
    logged_mode = MODE_SHADOW if mode in (MODE_SHADOW, MODE_SHADOW_CHILD) else mode
    if reason is not None:
        return "", _skip_record(payload, logged_mode, reason)
    if mode == MODE_SHADOW:
        spawn(raw_stdin)
        return "", None

    return _run(payload, env, mode=mode, logged_mode=logged_mode, client=client)


def _run(
    payload: Mapping[str, Any],
    env: Mapping[str, str],
    *,
    mode: str,
    logged_mode: str,
    client: router_mod.Client | None,
) -> tuple[str, dict[str, Any] | None]:
    started = time.monotonic()
    prompt = str(payload.get("prompt") or "")
    cwd = str(payload.get("cwd") or "")
    config = config_dir(env)
    skills = roster_mod.build_roster(
        user_skills_dir=(config / "skills") if config else None,
        plugins_manifest=(config / "plugins" / "installed_plugins.json") if config else None,
        settings_path=(config / "settings.json") if config else None,
        cwd=Path(cwd) if cwd else None,
    )
    if client is None:
        client = JevClient(resolve_api_key(env), base_url=env.get("TYPESAFE_BASE_URL"))

    budget = INJECT_BUDGET_S if mode == MODE_INJECT else SHADOW_BUDGET_S
    try:
        result = router_mod.suggest(client, prompt, skills, budget=budget)
        reason = result.reason
    except Exception as exc:  # noqa: BLE001 - fail-open: every failure becomes a logged row
        result = router_mod.Suggestion()
        reason = f"error: {type(exc).__name__}: {exc}"

    # The winning name comes back out of an HTTP response body. Nothing between that field
    # and the model's context checks it, so check it here: only a name the local roster
    # actually holds may be spoken, which also means the API can never widen what gets said.
    if result.name is not None and result.name not in {skill.name for skill in skills}:
        reason = f"suggestion not in roster: {result.name[:60]!r}"
        result.name = None

    elapsed_ms = int((time.monotonic() - started) * 1000)
    over_budget = mode == MODE_INJECT and elapsed_ms > INJECT_BUDGET_S * 1000
    if over_budget and result.name is not None:
        reason = f"over budget: {elapsed_ms}ms > {int(INJECT_BUDGET_S * 1000)}ms"
        result.name = None

    record = decision_log.build_record(
        project=cwd,
        session=str(payload.get("session_id") or ""),
        mode=logged_mode,
        model=router_mod.MODEL,
        router_version=router_mod.ROUTER_VERSION,
        question_hash=router_mod.QUESTION_HASH,
        roster_hash=roster_mod.roster_hash(skills),
        n_skills=len(skills),
        n_by_source=roster_mod.n_by_source(skills),
        prompt=prompt,
        elapsed_ms=elapsed_ms,
        suggestion=result.name,
        reason=reason,
        gate=result.gate,
        gate_values=result.gate_values,
        shortlist=result.shortlist,
        fits=result.fits,
        winner=result.winner,
        chunks=result.chunks,
        usage=result.usage,
    )
    if mode != MODE_INJECT or result.name is None:
        return "", record
    envelope = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": router_mod.suggestion_block(result.name),
        }
    }
    return json.dumps(envelope, ensure_ascii=False), record


def write_log(env: Mapping[str, str], record: dict[str, Any] | None) -> bool:
    """Append the row if there is one. A failure here is silent by design — the log is the
    instrument, and a broken instrument must not break the prompt it is measuring."""
    if record is None:
        return False
    path = log_path(env)
    if path is None:
        return False
    return decision_log.append(path, record)


def main() -> int:
    try:
        raw = sys.stdin.read()
        stdout, record = route(raw, os.environ)
        write_log(os.environ, record)
        if stdout:
            sys.stdout.write(stdout)
    except Exception:  # noqa: BLE001 - the hook contract is exit 0, always
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
