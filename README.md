**English** | [日本語](README.ja.md)

# jev-skill-router

A Claude Code hook that asks a fast probability model which of your installed skills fits the prompt, and logs the answer before it reaches the agent.

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

jev-skill-router is a Claude Code plugin for people who have dozens of skills installed. On every prompt, a `UserPromptSubmit` hook sends the prompt and your skill roster to [TypeSafe](https://typesafe.ai)'s Jev model, which answers typed questions with probabilities instead of text. Code reads those probabilities and names at most one skill, or none. It is Python 3.10+, standard library only, MIT licensed, version 0.2.0, and experimental.

**Read this before installing.** We built it, ran it, and concluded that as a router it is unlikely to help a strong model in Claude Code. It is published as a working reference and a measuring instrument, with the reasons written down below, so that anyone considering the same idea can start from what we found. It runs in **shadow mode** by default: it records what it would have suggested and injects nothing.

## What we learned by running it

**It cannot replace Claude Code's own skill selection.** A `UserPromptSubmit` hook can add text to a turn and nothing else. Claude Code still lists every skill's description to the model, and the model still chooses. The router runs alongside that choice. The tokens spent on the skill listing do not go down by one.

**The cookbook's conditions do not carry over.** In TypeSafe's experiment the agent was `claude-haiku-4-5` reading a skill index cut to 60 characters per skill, so a second reader with the full text had something to add. Claude Code shows the model each skill's whole description (up to 1,536 characters, per [the skills docs](https://code.claude.com/docs/en/skills)). Here the router is a weaker judge advising a stronger one that already sees the same descriptions. The only information it adds is the body of `SKILL.md`.

**What we measured** (all on 2026-09-21, author's own roster of 50 to 59 skills, `jev-1.13.0`, prompts in Japanese):

- Scripted single-intent requests ("record this decision as an ADR"): 6 of 6 sensible on 0.2.0. Five named the skill a person would pick, with fit answers of 0.93 to 0.98, and a thank-you message was correctly left alone.
- The author's real session, 0.1.0 in shadow mode: 6 prompts, 3 sensible and 3 wrong. The wrong ones were mid-conversation follow-ups ("why did you add that guardrail?"), which are most of what a real session contains. The gate scored them 0.34 to 0.64 as if a skill were wanted, and in all three the ranking's winner and the best per-candidate fit disagreed.
- The six real-session rows are an anecdote, not a rate. They are here because they are the only real-session data this project has. They come from 0.1.0, which ranked on truncated text; the real session has not been re-run on 0.2.0, and by this project's own rule rows from different versions are not pooled.

**What it may still be good for.** If a model fails to use skills because it does the work itself rather than because it picks the wrong one, a per-turn pointer acts as a nudge, not as information. The shadow log can tell those two cases apart (see "Reading your own log"). That is why the author keeps it running in shadow mode, and it will be removed if the log does not show it.

**If you want to change what the model sees**, this is not the tool. Two mechanisms do that:

- The official `skillOverrides` setting lists a skill to the model by name and description, by name only, or not at all ([skills docs](https://code.claude.com/docs/en/skills), values `on` / `name-only` / `user-invocable-only` / `off`, checked 2026-09-21).
- Claude Code's early-access function hooks ("mods", [design thread](https://github.com/anthropics/claude-code/issues/91870)) expose the skill listing as a rewritable attachment: `mods/types/claude-code.d.ts` in `anthropics/claude-code` names the kind `skill_listing` under `prompt.attachment` (checked 2026-09-21). A mod that does this already exists: [jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) in `davila7/claude-code-templates` (first commit 2026-09-19) withholds the listing from the model, lets Jev pick at most one skill with the same cookbook recipe, attaches that skill's `SKILL.md`, and hides the skills with `skillOverrides`. Its README says the listing hook always gives the same answer, so the model's prompt cache holds. We have not tried function hooks or that mod, and cannot say whether it works. This project uses neither mechanism.

## Install

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

Claude Code asks for three options when it enables the plugin: a TypeSafe API key ([create one here](https://console.typesafe.ai/keys); stored in your system keychain), the mode (`shadow` by default), and an optional log path. The mode picker needs Claude Code 2.1.271 or newer; on an older build the mode stays `shadow` unless you set the `JEV_ROUTER` environment variable to `inject` or `off`. You can also pass the key as `TYPESAFE_API_KEY`, or keep it in `~/.config/typesafe/api_key`. Setting `JEV_ROUTER=off` in the environment turns the hook off for one process, which is how you keep an unattended script out of it.

To run it without the plugin system, see the manual wiring in [the operating manual](skills/jev-skill-router/SKILL.md#install).

## How it decides

The recipe is TypeSafe's published [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion), ported to a Claude Code hook. Question text and thresholds are copied from it and kept as constants in one file. The cookbook's 60-character index is not copied: that width is what the agent it was written against shows in its own skill index, while Claude Code shows the model the whole description. Ranking on a prefix would rank on less than the agent already sees, so nothing is truncated here.

1. **Wide.** One request ranks the whole roster by name and whole description, and asks three yes/no questions about the prompt itself: does it act on the user's system, would an expert follow a documented procedure, would prose alone be enough. If their mean is under 0.30, the hook stops. No skill is needed and no second request is spent.
2. **Narrow.** The top three go back with their whole description and the whole body of their `SKILL.md`. The model picks one, and answers one more question per candidate: does this skill do the specific thing asked? If the best answer is under 0.30, nothing is suggested.

The roster is built from three places: your user skills, the skills of plugins that are enabled in your settings, and project skills found from the session's working directory up to the git root. Skills marked `disable-model-invocation: true` are left out. The hook never edits the skill list Claude Code puts in the model's context. It only adds the one block shown below, so prompt caching over that list is unaffected.

Every failure exits 0: a missing key, a timeout or an API error costs one log line, never a turn. In `shadow` mode the hook hands the work to a detached child process and returns at once, so the turn is not delayed. `inject` mode has to wait for the answer and works under a 3 second wall-clock budget across all requests; six live decisions on 0.2.0 (2026-09-21) took 0.7 to 1.6 seconds.

## What one decision looks like

In every mode except `off`, each prompt appends one JSON line to `decisions.jsonl` in the plugin's data directory. This row is from a live call against `jev-1.13.0`, run in `inject` mode; the prompt (in Japanese) asked to record a design decision as an ADR. `gate` is the mean from step 1, `fits` holds the per-candidate answers from step 2, and both cleared 0.30, so a skill was named. The row is abridged here.

```json
{"mode": "inject", "model": "jev-1.13.0", "router_version": "0.2.0",
 "question_hash": "662772b42ed4",
 "n_skills": 52, "n_by_source": {"user": 45, "plugin": 7, "project": 0},
 "gate": 0.47, "shortlist": ["adr-writer", "adhd:adhd", "archify"],
 "fits": {"adr-writer": 0.93, "adhd:adhd": 0.14, "archify": 0.05},
 "suggestion": "adr-writer", "reason": "shortlist winner adr-writer (fits 0.93)",
 "usage": {"input_tokens": 21597, "output_tokens": 702, "calls": 2},
 "elapsed_ms": 1567}
```

The prompt text is never written to the log, only its hash and length. In `shadow` mode the row is all that happens. In `inject` mode the decision also adds this block to the turn, and nothing at all when no skill clears the thresholds:

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## What leaves your machine

Each routed prompt sends to `api.typesafe.ai`: the full prompt text, every roster skill's name and whole description, and, for the top three only, **the whole text of their `SKILL.md`** — including skills that live in a private project's `.claude/skills/`. Conversation history, your project files and tool output are never sent.

In your own `~/.claude/skills/` and in a plugin, a skill directory may be a symlink and is followed. In a project's `.claude/skills/`, which belongs to whoever wrote the repository, a `SKILL.md` that resolves outside that directory is left out, so a link to another file on your machine is never read or sent. The project's own skill files still are: in a repository you did not write, treat `.claude/skills/` as part of what a routed prompt can send.

**A secret pasted into a prompt is sent as typed.** There is no scrubbing step. The endpoint host is pinned in code and redirects are refused, so an environment variable cannot send your key or prompt to another host.

## Limits

- The thresholds are the cookbook's starting values, measured by the vendor on an English roster with an earlier model version. They are not calibrated for your roster or language. That is what shadow mode is for.
- This repository has no evidence that injecting the suggestion improves anything. The cookbook reports the vendor's experiment, including cases where the suggestion broke a turn the agent had been getting right, under conditions that differ from Claude Code's (see "What we learned by running it").
- Skills that are built in, with no `SKILL.md` on disk, and skills under `--add-dir` directories cannot be suggested.
- Prompts starting with `/` and prompts over 4000 characters are skipped.
- Jev takes 64k tokens per request, and 32k for the state plus the longest question. Two inputs can reach that: three unusually long `SKILL.md` files in one shortlist, and a roster past the 240-skill chunk size, whose wide question carries that many whole descriptions. Nothing measures the request beforehand — the API answers with an error, the turn passes with no suggestion, and the log row carries the reason.
- TypeSafe is a paid third-party API and every routed prompt costs one or two requests. On 0.2.0 with a roster of 52 to 59 skills (2026-09-21), a prompt used about 10,000 input tokens when the first step stopped and 21,600 to 25,300 when both steps ran. Check [TypeSafe's pricing](https://docs.typesafe.ai/models) for current rates and limits; this README does not quote them because they change.

## Reading your own log

Rows that differ in `model`, `router_version` or `question_hash` come from a different judge, so read them separately. To decide whether `inject` is worth turning on, join the log by `session` and time against your own record of which skills each session used, and read three counts: suggested and used, suggested but unused, used but not suggested. A missing log means unmeasured, not zero suggestions.

## Related work

- The recipe comes from the [TypeSafe skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion).
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) implements the same cookbook for Hermes Agent. Two findings come from its documentation: a single question is capped at 255 choices, so large rosters are chunked, and the ranking and the per-candidate fit can disagree. No code was copied from it.
- Other routers exist for Claude Code, among them [skillranker](https://github.com/Dicklesworthstone/skillranker), a Rust CLI with local history and calibration commands. [typesafe-mod](https://github.com/BeLazy167/typesafe-mod) does the same per-prompt ranking as a function-hooks mod, and shares the limit described above: it adds a line and leaves the listing alone. [jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) goes further and replaces the listing, as described under "What we learned by running it"; the same repository has [jev-model-router](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-model-router), which routes model and effort with Jev. This one has no packages to install (it still needs the TypeSafe API), installs with `/plugin install`, sees plugin and project skills, and logs before it speaks.

## Provenance

This project is not affiliated with TypeSafe AI. The code was written with Claude Code under the author's direction. It is checked by an offline test suite (`uv run pytest -q`, no network needed). The paths that carry the key and the prompt were reviewed by automated reviewers (an LLM security-review agent and Claude Code's built-in code review), which found and led to fixes for a key leak on HTTP redirects and for untrusted strings reaching the model's context. No independent human audit has been done.

## More

- [Operating manual](skills/jev-skill-router/SKILL.md): every mode, option, log field and skip condition
- [Changelog](CHANGELOG.md)
- License: [MIT](LICENSE)
