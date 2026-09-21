**English** | [日本語](README.ja.md)

# jev-skill-router

A Claude Code hook that asks a fast probability model which of your installed skills fits the prompt, and logs the answer before it reaches the agent.

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

jev-skill-router is a Claude Code plugin for people who have dozens of skills installed. On every prompt, a `UserPromptSubmit` hook sends the prompt and your skill roster to [TypeSafe](https://typesafe.ai)'s Jev model, which answers typed questions with probabilities instead of text. Code reads those probabilities and names at most one skill, or none. It is Python 3.10+, standard library only, MIT licensed, version 0.1.0, and experimental.

Claude Code shows the model a one-line description of every skill and leaves the choice to it. As the list grows, the model reads past the skill that fits, or loads one when nothing does. This plugin turns that choice into a separate, inspectable decision. It starts in **shadow mode**: it records what it would have suggested and injects nothing, so you can compare its picks with what your sessions actually used before you switch it on.

## Install

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

Claude Code asks for three options when it enables the plugin: a TypeSafe API key ([create one here](https://console.typesafe.ai/keys); stored in your system keychain), the mode (`shadow` by default), and an optional log path. The mode picker needs Claude Code 2.1.271 or newer; on an older build the mode stays `shadow` unless you set the `JEV_ROUTER` environment variable to `inject` or `off`. You can also pass the key as `TYPESAFE_API_KEY`, or keep it in `~/.config/typesafe/api_key`. Setting `JEV_ROUTER=off` in the environment turns the hook off for one process, which is how you keep an unattended script out of it.

To run it without the plugin system, see the manual wiring in [the operating manual](skills/jev-skill-router/SKILL.md#install).

## How it decides

The recipe is TypeSafe's published [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion), ported to a Claude Code hook. Question text and thresholds are copied from it and kept as constants in one file.

1. **Wide.** One request ranks the whole roster by name and the first 60 characters of each description, and asks three yes/no questions about the prompt itself: does it act on the user's system, would an expert follow a documented procedure, would prose alone be enough. If their mean is under 0.30, the hook stops. No skill is needed and no second request is spent.
2. **Narrow.** The top three go back with their full descriptions and the first 700 characters of each `SKILL.md`. The model picks one, and answers one more question per candidate: does this skill do the specific thing asked? If the best answer is under 0.30, nothing is suggested.

The roster is built from three places: your user skills, the skills of plugins that are enabled in your settings, and project skills found from the session's working directory up to the git root. Skills marked `disable-model-invocation: true` are left out. The hook never edits the skill list Claude Code puts in the model's context. It only adds the one block shown below, so prompt caching over that list is unaffected.

Every failure exits 0: a missing key, a timeout or an API error costs one log line, never a turn. In `shadow` mode the hook hands the work to a detached child process and returns at once, so the turn is not delayed. `inject` mode has to wait for the answer and works under a 3 second wall-clock budget across all requests; the three live decisions made on 2026-09-21 took 0.5 to 1.3 seconds.

## What one decision looks like

In every mode except `off`, each prompt appends one JSON line to `decisions.jsonl` in the plugin's data directory. This row is from a live call against `jev-1.13.0`, run in `inject` mode; the prompt (in Japanese) asked to record a design decision as an ADR. `gate` is the mean from step 1, `fits` holds the per-candidate answers from step 2, and both cleared 0.30, so a skill was named. The row is abridged here.

```json
{"mode": "inject", "model": "jev-1.13.0", "question_hash": "662772b42ed4",
 "n_skills": 50, "n_by_source": {"user": 45, "plugin": 5, "project": 0},
 "gate": 0.4833, "shortlist": ["adr-writer", "adhd:adhd", "archify"],
 "fits": {"adr-writer": 0.93, "adhd:adhd": 0.15, "archify": 0.05},
 "suggestion": "adr-writer", "elapsed_ms": 1329}
```

The prompt text is never written to the log, only its hash and length. In `shadow` mode the row is all that happens. In `inject` mode the decision also adds this block to the turn, and nothing at all when no skill clears the thresholds:

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## What leaves your machine

Each routed prompt sends to `api.typesafe.ai`: the full prompt text, every roster skill's name and 60-character description, and, for the top three only, the full description and the first 700 characters of `SKILL.md`. Conversation history, your project files and tool output are never sent.

**A secret pasted into a prompt is sent as typed.** There is no scrubbing step. The endpoint host is pinned in code and redirects are refused, so an environment variable cannot send your key or prompt to another host.

## Limits

- The thresholds are the cookbook's starting values, measured by the vendor on an English roster with an earlier model version. They are not calibrated for your roster or language. That is what shadow mode is for.
- This repository has no effectiveness numbers of its own yet. The cookbook reports the vendor's experiment, including cases where the suggestion broke a turn the agent had been getting right. Treat it as the direction on their roster, not a result on yours.
- Skills that are built in, with no `SKILL.md` on disk, and skills under `--add-dir` directories cannot be suggested.
- Prompts starting with `/` and prompts over 4000 characters are skipped.
- TypeSafe is a paid third-party API and every routed prompt costs one or two requests. With a 50-skill roster the live decisions above used about 2,400 input tokens when the first step stopped and 4,200 to 4,800 when both steps ran. Check [TypeSafe's pricing](https://docs.typesafe.ai/models) for current rates and limits; this README does not quote them because they change.

## Reading your own log

Rows that differ in `model`, `router_version` or `question_hash` come from a different judge, so read them separately. To decide whether `inject` is worth turning on, join the log by `session` and time against your own record of which skills each session used, and read three counts: suggested and used, suggested but unused, used but not suggested. A missing log means unmeasured, not zero suggestions.

## Related work

- The recipe comes from the [TypeSafe skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion).
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) implements the same cookbook for Hermes Agent. Two findings come from its documentation: a single question is capped at 255 choices, so large rosters are chunked, and the ranking and the per-candidate fit can disagree. No code was copied from it.
- Other routers exist for Claude Code, among them [skillranker](https://github.com/Dicklesworthstone/skillranker), a Rust CLI with local history and calibration commands. This one is for people who want a hook with no packages to install (it still needs the TypeSafe API) that installs with `/plugin install`, sees plugin and project skills, and measures before it speaks.

## Provenance

This project is not affiliated with TypeSafe AI. The code was written with Claude Code under the author's direction. It is checked by an offline test suite (`uv run pytest -q`, no network needed). The paths that carry the key and the prompt were reviewed by automated reviewers (an LLM security-review agent and Claude Code's built-in code review), which found and led to fixes for a key leak on HTTP redirects and for untrusted strings reaching the model's context. No independent human audit has been done.

## More

- [Operating manual](skills/jev-skill-router/SKILL.md): every mode, option, log field and skip condition
- [Changelog](CHANGELOG.md)
- License: [MIT](LICENSE)
