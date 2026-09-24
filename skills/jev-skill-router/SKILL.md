---
name: jev-skill-router
description: >
  A Claude Code UserPromptSubmit hook that asks TypeSafe Jev which installed skill (user,
  plugin or project) fits the prompt — two typed requests, at most one skill name back — and
  either records the decision (shadow) or injects a one-line pointer (inject). Not invoked by
  the model: it runs as a hook (plugin install, or one line in settings.json) and this file is
  its operating manual.
origin: shimo4228
replaces: >
  TypeSafe cookbook "Skill suggestion"
  (https://docs.typesafe.ai/cookbooks/skill_suggestion.md, fetched 2026-09-21) — source of the
  question text, state shape, two-request structure, thresholds and the <skill_relevance> block.
  DECRUX9812/typesafe-skill-router@f150284 (MIT) — credit for two findings the cookbook does not
  have: the 255-choice cap per question, and the margin rule for when Choice and fits disagree.
  No code was copied from it.
disable-model-invocation: true
user-invocable: false
---

# jev-skill-router

Claude Code lists every installed skill's description and leaves the choice to the model. With
dozens of skills the model reads past the one that fits, or loads one when none does. This hook
makes that choice a separate, typed judgment: the prompt and the skill roster go to TypeSafe's
Jev model, which returns probabilities, and code decides from them. The roster in the model's
context never changes — at most one line is added to the turn.

Python 3.10+, standard library only. The runtime is `scripts/`; nothing else is needed.

## Install

As a plugin (wires the hook for you):

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

Claude Code asks for the options when it enables the plugin: a TypeSafe API key
(https://console.typesafe.ai/keys — stored in the system keychain, optional if you pass the key
another way), the mode (`shadow` by default; the picker needs Claude Code 2.1.271+), and an
optional log path.

By hand: put this directory anywhere and add one hook to `~/.claude/settings.json`:

```json
{
  "env": { "JEV_ROUTER": "shadow" },
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command",
                     "command": "python3 /path/to/jev-skill-router/scripts/route.py",
                     "timeout": 5 } ] }
    ]
  }
}
```

Where each setting comes from, first match wins:

| Setting | Sources |
|---|---|
| mode | env `JEV_ROUTER` → plugin option `mode` → `shadow`. The environment variable wins so one unattended script can set `JEV_ROUTER=off` for itself |
| API key | env `TYPESAFE_API_KEY` → plugin option `api_key` → the file named by env `JEV_ROUTER_KEY_FILE` → `~/.config/typesafe/api_key` (mode 0600; a bare key or a `TYPESAFE_API_KEY=...` line) |
| log file | env `JEV_ROUTER_LOG` → plugin option `log_path` → `decisions.jsonl` in the plugin's data directory → `~/.claude/metrics/jev-decisions.jsonl` |

Start in `shadow`. Switch to `inject` after reading your own log (see "Reading the log").

## Modes

| `JEV_ROUTER` | What happens on each prompt |
|---|---|
| `off` | Nothing. No request, no log line. |
| `shadow` (also when unset) | The hook re-launches itself detached and exits at once, so the prompt is never delayed. The child asks Jev and appends one log line. Nothing reaches the model. |
| `inject` | Synchronous, 3 s wall-clock budget across all requests. When a skill clears both thresholds, the hook emits the cookbook's `<skill_relevance>` block as `additionalContext`. When nothing fits, or the budget runs out, it emits nothing. |

Skipped without calling Jev, each leaving a log row with the cause in `reason`: an unrecognised
`JEV_ROUTER` value (a typo never turns into injection or traffic), an empty prompt, prompts
starting with `/`, prompts over 4000 characters, a missing key, and sessions whose cwd is under a
prefix listed in env `JEV_ROUTER_SKIP_CWD_PREFIX` (colon-separated, empty by default — use it to
keep test sandboxes and fixture runs away from the API).

Every failure path exits 0. A routing problem costs a log line, never a turn.

## How a decision is made

1. **Wide.** One `Choice` over the whole roster (each skill's name and its whole description)
   and three `Noul` questions about the request itself — does it act on the user's system,
   would an expert follow a documented procedure, would prose alone suffice (inverted). Their
   mean is the gate; under 0.30 the hook stops: no skill needed, no second request.
2. **Narrow.** The top 3 go back with their whole description and their whole SKILL.md body:
   one `Choice`, plus one `Noul` per candidate — does this skill do the specific thing asked?
   If the best fit is under 0.30, nothing is suggested.

Nothing is truncated on the way out. The cookbook this is ported from cuts each description to
60 characters because that is the width its own agent displays; Claude Code puts the whole
description in the model's context, so ranking on a prefix would rank on less than the agent
sees. On this machine's 59-skill roster, two descriptions fit in 60 characters (2026-09-21).

Rosters over 240 skills are split into chunks (the API caps one question at 255 choices); each
chunk carries a `none_of_these` option and nominates nobody when that option reaches 0.50 —
except the chunk holding the single most probable skill, which always nominates, so a fitting
skill is never lost to chunking.
A margin rule for the case where the `Choice` winner and the best-fitting candidate differ is
implemented and off by default (`FITS_MARGIN_DEFAULT = None` in `scripts/router.py`).

Question text, thresholds, the model pin (`jev-1.13.0`) and `ROUTER_VERSION` are constants at
the top of `scripts/router.py`. The thresholds are the cookbook's starting values, measured by
the vendor on `jev-1.12` with an English roster — treat them as a starting point, not a
calibration.

## The roster

| Source | Found at | Name in the roster |
|---|---|---|
| user | `~/.claude/skills/*/SKILL.md` (symlinked skill directories are followed) | directory name |
| plugin | install paths in `~/.claude/plugins/installed_plugins.json` whose plugin is `true` in `enabledPlugins` (user, project and local settings merged) → `skills/*/SKILL.md` | `<plugin>:<directory name>` |
| project | every `.claude/skills/*/SKILL.md` from the session cwd up to the git root (24 levels up when there is no git root), resolving inside the repository level that holds that `.claude/`; the nearest directory wins a name clash, and a project skill shadows a user skill of the same name | directory name |

Left out: this skill, skills with `disable-model-invocation: true`, `~/.claude/skills/synced/`,
and directory names that are not plain identifiers (a name is injected into the model's context,
so it is validated before it enters the roster). `CLAUDE_CONFIG_DIR` relocates `~/.claude` for
roster discovery only; the log location is resolved as in the table under "Install".

## What leaves the machine

Each routed prompt sends to `https://api.typesafe.ai`: the full prompt text, every roster
skill's name and whole description, and — for the top 3 only — **the whole body of their
SKILL.md** (the text after its frontmatter), including skills that live in a private project's `.claude/skills/`. Conversation
history, files, tool output and the key file's path are never sent.

In your own `~/.claude/skills/` and in a plugin, a skill directory may be a symlink and is
followed. In a project's `.claude/skills/`, which belongs to whoever wrote the repo, a `SKILL.md` is read
only if it resolves inside that repository level (the directory holding `.claude/`), so a link to a
file elsewhere on your machine is never read or sent. A link to another file inside the same
repository is followed, including one you added and never committed, such as `.env`: in a repo
you did not write, treat `.claude/skills/` and anything in the repository it can link to as part
of what a routed prompt can send.

**A secret pasted into a prompt is sent as typed.** There is no scrubbing step. Unattended
sessions (cron, launchd, `claude -p`) are routed like interactive ones unless they set
`JEV_ROUTER=off`.

The endpoint host is pinned: `TYPESAFE_BASE_URL` may change the path or point at a loopback stub
(plain `http://` is allowed only there), but any other host is refused before the key is
attached — one environment variable cannot redirect the key and the prompt elsewhere. A 30x answer is refused
instead of followed, so the key is never re-sent to a redirect target.

## Reading the log

One JSON line per routed or skipped prompt, appended to the log file resolved under "Install"
(created 0600, its directory 0700; a symlinked path is refused). The prompt text is never
written — only `prompt_sha` and `prompt_chars`.

| Field | Meaning |
|---|---|
| `ts`, `project`, `session`, `mode` | when, which cwd, which Claude Code session, which mode |
| `model`, `router_version`, `question_hash` | the judge's version. Rows that differ in any of the three are a different distribution — read them separately |
| `roster_hash`, `n_skills`, `n_by_source` | which roster was judged |
| `gate`, `gate_values`, `shortlist`, `fits`, `winner` | the raw probabilities |
| `suggestion`, `reason` | the skill named (or null) and why — threshold miss, skip cause, or error |
| `chunks`, `usage`, `elapsed_ms` | requests spent, tokens, wall-clock |

The log only accumulates; nothing reads it back. To decide whether `inject` is worth turning on,
join it by `session` and `ts` against your own record of which skills the session actually used
(a PostToolUse log of `Skill` calls is enough) and read three counts: suggestion = skill used, suggestion but no skill
used, skill used but no suggestion. A missing log means unmeasured, never zero suggestions.

## Limits

- Built-in skills with no SKILL.md on disk, and skills under `--add-dir` directories (not in the
  hook input), cannot be suggested.
- Thresholds are uncalibrated for your roster and language. TypeSafe documents that CJK input is
  not at parity with English.
- Jev takes 64k tokens per request, and 32k for `state` plus the longest question. Two inputs
  can reach that: three unusually long SKILL.md files in one shortlist, and — on a roster past
  the 240-skill chunk size — a wide question carrying that many whole descriptions. Nothing
  measures the request beforehand: the API answers with an error, the turn passes with no
  suggestion, and the log row carries the reason.
- The 4xx/5xx error body shape is read defensively and has not been observed live; the success
  path was confirmed against the live API on 2026-09-21.

## Development

```bash
uv run pytest -q
```

Tests never touch the network — the client is scripted. `tests/golden/inject-envelope.json`
freezes the one output a machine parses; update it only when the task is to change that output.
