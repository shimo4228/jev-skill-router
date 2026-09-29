**English** | [日本語](README.ja.md)

# jev-skill-router

A Claude Code hook that asks Jev, TypeSafe's fast probability model, which of your installed skills fits each prompt, and logs the answer; it tells Claude only if you opt in. Published as an experiment: running it showed it is unlikely to help a strong model, and this README says why.

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="assets/overview.svg" width="760" alt="How it works, in four panels: you type a prompt; Jev guesses which skill fits, for example adr-writer at 93%; in shadow mode the guess is only logged, in inject mode Claude also gets a one-line hint; underneath, Claude still sees every skill and makes the final pick.">
</p>

jev-skill-router is a Claude Code plugin for people who have dozens of skills installed and find that the model sometimes skips the one that fits. On every prompt, a `UserPromptSubmit` hook sends the prompt and your skill roster to [TypeSafe](https://typesafe.ai)'s Jev model, which never writes text: it answers questions with a fixed set of answers (yes or no, or one pick from a list) with probabilities. Code reads those probabilities and names at most one skill, or none. Claude still sees all your skills and makes the final choice itself. It is Python 3.10+, standard library only, MIT licensed, version 0.2.0, and experimental.

**Read this before installing.** It is published as a working reference and a measuring instrument, so that anyone considering the same idea can start from what we found. It runs in **shadow mode** by default: it records what it would have suggested and injects nothing, so its log can be checked against the skills your sessions actually used. What running it showed, and why it stops short of rewriting Claude Code's skill listing, is in the article [I Added Jev's Skill Router to Claude Code and Turned Back Just Before Rewriting the Skill Listing](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in) ([Japanese](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)). Other experiments with Jev are under [More from the author](#more-from-the-author).

## What we learned by running it

**It cannot replace Claude Code's own skill selection.** A `UserPromptSubmit` hook can add text to a turn (or block the prompt), but it cannot change the skill listing. Claude Code still lists every skill's description to the model, and the model still chooses. The router runs alongside that choice. The tokens spent on the skill listing do not go down by one.

**The conditions of TypeSafe's recipe do not carry over.** The router ports TypeSafe's [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion). In TypeSafe's experiment the agent was `claude-haiku-4-5` reading a skill index cut to 60 characters per skill, so a second reader with the full text had something to add. Claude Code shows the model each skill's description, up to 1,536 characters ([skills docs](https://code.claude.com/docs/en/skills), checked 2026-09-21). Here the router is a weaker judge ([measured against Opus](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)) advising a stronger one that already sees the same descriptions. What it adds is the body of `SKILL.md`, plus any part of a description past that 1,536-character cut.

**What we measured** (all on 2026-09-21, author's own roster of 50 to 59 skills, `jev-1.13.0`, prompts in Japanese; the skills the author wrote are public in [claude-harness](https://github.com/shimo4228/claude-harness)):

- Scripted single-intent requests ("record this decision as an ADR"): 6 of 6 sensible on 0.2.0. Five named the skill a person would pick, with fit answers (Jev's probability that the skill does the specific thing asked) of 0.93 to 0.98, and a thank-you message was correctly left alone.
- The author's real session, 0.1.0 in shadow mode: 6 prompts, 3 sensible and 3 wrong. The wrong ones were mid-conversation follow-ups ("why did you add that guardrail?"), the kind of prompt that fills most of the author's own sessions. The router's first check, the gate, stops when its score is under 0.30; it scored these three 0.34 to 0.64, as if a skill were wanted. In all three, Jev's pick and the candidate with the best fit also disagreed (see "How it decides").
- The six real-session rows are an anecdote, not a rate. They are here because they are the only real-session data this project has. They come from 0.1.0, which ranked on truncated text; the real session has not been re-run on 0.2.0, and log rows from different versions are kept apart rather than pooled.

**What it may still be good for.** If a model fails to use skills because it does the work itself rather than because it picks the wrong one, a per-turn pointer acts as a nudge, not as information. The shadow log, joined with the session transcripts, can tell those two cases apart (see "Reading your own log"). The pattern to look for is sensible suggestions on turns where the session used no skill at all.

**A week in shadow mode did not show that pattern, and the author removed the router from their own setup** on 2026-09-28. Of 539 suggestions in 1,242 decisions, 28 were followed within 30 minutes by a call of the suggested skill, about 5% (26 when calls inside subagents are left out). The author then read 20 of the unused suggestions: 13 were off target, and one may have been a miss by Claude Code. The script and the numbers are in [evals/](evals/README.md). The account is in the article [「これ意味あるかな？」Claude Codeに入れたJevのプラグインを1週間で外すまで](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify) (Japanese).

**If you want to change what the model sees**, this is not the tool. Besides editing each skill's own frontmatter, two mechanisms do that, and this project uses neither:

- The official `skillOverrides` setting lists a skill to the model by name and description, by name only, or not at all ([skills docs](https://code.claude.com/docs/en/skills), values `on` / `name-only` / `user-invocable-only` / `off`, checked 2026-09-21).
- Claude Code's early-access function hooks ("mods", [design thread](https://github.com/anthropics/claude-code/issues/91870)) can rewrite the skill listing before the model sees it (checked 2026-09-21 against the mod type definitions in `anthropics/claude-code`).

A mod that combines both mechanisms already exists: [jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) in `davila7/claude-code-templates` (first commit 2026-09-19). It withholds the listing from the model, lets Jev pick at most one skill with the same cookbook recipe, attaches that skill's `SKILL.md`, and hides the skills with `skillOverrides`. Its README says the listing hook always gives the same answer, so the model's prompt cache holds. We have not tried function hooks or that mod, and cannot say whether it works.

## Install

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

Claude Code asks for three options when it enables the plugin: a TypeSafe API key (a paid API, see Limits; [create one here](https://console.typesafe.ai/keys); stored in your system keychain), the mode (`shadow` by default), and an optional log path. The mode picker needs Claude Code 2.1.271 or newer; on an older build the mode stays `shadow` unless you set the `JEV_ROUTER` environment variable to `inject` or `off`. You can also pass the key as `TYPESAFE_API_KEY`, or keep it in `~/.config/typesafe/api_key`. Setting `JEV_ROUTER=off` in the environment turns the hook off for one process, which is how you keep an unattended script out of it.

To run it without the plugin system, see the manual wiring in [the operating manual](skills/jev-skill-router/SKILL.md#install).

## How it decides

Question text and thresholds are copied from the cookbook and kept as constants in one file. It does not copy the cookbook's 60-character index: ranking on a prefix would rank on less than Claude already sees (see "What we learned by running it"), so nothing is truncated here.

1. **Wide.** One request ranks the whole roster by name and whole description (a roster over 240 skills is split into one request per 240). The same request asks three yes/no questions about the prompt itself: does it act on the user's system, would an expert follow a documented procedure, would prose alone be enough. The third answer is flipped, so that a high score always points to a skill. The mean of the three is the gate: under 0.30, the hook stops. No skill is needed and no second request is spent.
2. **Narrow.** The top three go back with their whole description and the whole body of their `SKILL.md`. Jev picks one, and answers one more question per candidate: does this skill do the specific thing asked? That answer is the candidate's fit. If the best fit is under 0.30, nothing is suggested. Otherwise Jev's pick is named, even when another candidate has the higher fit; the log row then names both.

The roster is built from three places: your user skills, the skills of plugins that are enabled in your settings, and project skills found from the session's working directory up to the git root (outside a git repository, up to 24 levels up). Skills marked `disable-model-invocation: true` are left out. The hook only adds the one block shown below, so prompt caching over Claude Code's skill listing is unaffected.

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

The prompt text is never written to the log, only its hash and length (`prompt_sha` and `prompt_chars`, left out of the row above; `question_hash` identifies the router's question set, not the prompt). In `shadow` mode the row is all that happens. In `inject` mode the decision also adds the block below to the turn. When no skill clears the thresholds, it adds nothing.

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## What leaves your machine

Each routed prompt sends to `api.typesafe.ai`: the full prompt text, every roster skill's name and whole description, and, for the top three only, **the whole body of their `SKILL.md`**, including skills that live in a private project's `.claude/skills/`. Conversation history and tool output are never sent. Your project's other files are not sent either, except through a skill link, described next.

In a repository you did not write, treat `.claude/skills/`, and anything in that repository it can link to, as part of what a routed prompt can send. That includes a file you added yourself and never committed, such as `.env`. The rule behind this: in your own `~/.claude/skills/` and in a plugin, symlinked skill directories are followed. A project's `.claude/skills/` belongs to whoever wrote the repository, so a project `SKILL.md` is read only if it resolves inside that repository (the directory holding `.claude/`). A project skill's link to a file elsewhere on your machine is never read or sent.

**A secret pasted into a prompt is sent as typed.** There is no scrubbing step. The endpoint host is pinned in code and redirects are refused, so no environment variable can send your key or prompt to another machine. The one exception is for tests and local stubs: `TYPESAFE_BASE_URL` may point at a loopback address (`localhost`, `127.0.0.1`, `::1`), and then both go to whatever listens on that port.

## Limits

- The thresholds are the cookbook's starting values, measured by the vendor on an English roster with an earlier model version. They are not calibrated for your roster or language. That is what shadow mode is for.
- This repository has no evidence that injecting the suggestion improves anything. The cookbook reports the vendor's experiment, including cases where the suggestion broke a turn the agent had been getting right, under conditions that differ from Claude Code's (see "What we learned by running it").
- Skills that are built in, with no `SKILL.md` on disk, and skills under `--add-dir` directories cannot be suggested.
- Prompts starting with `/` and prompts over 4000 characters are skipped.
- Jev accepts at most 64k tokens per request, and at most 32k for the prompt plus the longest question, which carries the candidates. Two inputs can reach that: three unusually long `SKILL.md` files in one shortlist, and a large roster, since one wide question carries up to 240 whole descriptions. Nothing measures the request beforehand — the API answers with an error, the turn passes with no suggestion, and the log row carries the reason.
- TypeSafe is a paid third-party API and every routed prompt costs one or two requests, plus one for every further 240 skills in the roster. On 0.2.0 with a roster of 52 to 59 skills (2026-09-21), a prompt used about 10,000 input tokens when the first step stopped and 21,600 to 25,300 when both steps ran. Check [TypeSafe's pricing](https://docs.typesafe.ai/models) for current rates and limits; this README does not quote them because they change.

## Reading your own log

Rows that differ in `model`, `router_version` or `question_hash` come from a different judge, so read them separately. To decide whether `inject` is worth turning on, join the log by `session` and time against which skills each session actually used (the router does not record that; Claude Code's session transcripts under `~/.claude/projects/` show every Skill tool call), and read three counts: suggested and used, suggested but unused, used but not suggested. The count that argues for `inject` is the second one, restricted to sensible suggestions on turns that used no other skill: those are the turns where a nudge could have helped. A missing log means unmeasured, not zero suggestions.

`python3 evals/shadow_join.py` does the join and prints the first two counts and the number of Skill calls. It cannot tell whether a suggestion was sensible: for that it draws a random sample of unused suggestions for you to read one by one. [evals/](evals/README.md) explains the options and shows the author's own week.

## Related work

- The recipe comes from the [TypeSafe skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion).
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) implements the same cookbook for Hermes Agent. Two findings come from its documentation: a single question is capped at 255 choices, so large rosters are chunked, and the ranking and the per-candidate fit can disagree. No code was copied from it.
- Other routers exist for Claude Code, among them [skillranker](https://github.com/Dicklesworthstone/skillranker), a Rust CLI with local history and calibration commands. [typesafe-mod](https://github.com/BeLazy167/typesafe-mod) does the same per-prompt ranking as a function-hooks mod, and shares the limit described above: it adds a line and leaves the listing alone. [jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) goes further and replaces the listing, as described under "What we learned by running it"; the same repository has [jev-model-router](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-model-router), which routes model and effort with Jev. This one installs with `/plugin install`, needs only Python's standard library (plus the TypeSafe API), includes plugin and project skills in its roster, and logs every decision before it tells Claude anything.

## More from the author

Each experiment with Jev, this router included, is written up as an article, in English on Dev.to and in Japanese on Zenn:

- [I Added Jev's Skill Router to Claude Code and Turned Back Just Before Rewriting the Skill Listing](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in) ([Japanese](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)). The story of this repository: what a prompt hook could change, where the author stopped, and three things to check before adding a decision model to your own harness.
- [How Close to Opus Does Jev, a Model That Writes No Text, Get at Skill Selection in 0.3 Seconds?](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj) ([Japanese](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)). Jev and Claude Opus pick skills for the same 150 situations. Jev agrees with Opus about half as often as Opus agrees with itself, at about 1/560th of the cost.
- [What Does It Take to Reproduce Jev's Decisions Locally?](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n) ([Japanese](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)). Four local models replay the same 150 selections, and all four fail, each for a different reason.
- [Moving My Research Pipeline's Judgment Calls from an LLM to Jev, a Judgment-Only Model](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj) ([Japanese](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)). Jev as the judge inside a daily research loop. The code is [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline).

The rest of the author's work, on how agents are built, who is accountable when they fail, and authorship in the AI age, starts at [github.com/shimo4228](https://github.com/shimo4228), where new experiments appear first. All articles: [Dev.to](https://dev.to/shimo4228) (English) and [Zenn](https://zenn.dev/shimo4228) (Japanese).

## Provenance

This project is not affiliated with TypeSafe AI. The code was written with Claude Code under the author's direction. It is checked by an offline test suite (`uv run pytest -q`, no network needed). The paths that carry the key and the prompt were reviewed by automated reviewers (an LLM security-review agent and Claude Code's built-in code review), which found and led to fixes for a key leak on HTTP redirects and for untrusted strings reaching the model's context. No independent human audit has been done.

## Documentation and license

- [Operating manual](skills/jev-skill-router/SKILL.md): every mode, option, log field and skip condition
- [Evals](evals/README.md): the script that joins the log with session transcripts, and the author's week in numbers
- [Changelog](CHANGELOG.md)
- License: [MIT](LICENSE)
