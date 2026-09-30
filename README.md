**English** | [日本語](README.ja.md)

# jev-skill-router

What happens when you add Jev to Claude Code as a skill router: the code, the log, and the week that ended with removing it.

[![tests](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml/badge.svg)](https://github.com/shimo4228/jev-skill-router/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![status: experiment concluded](https://img.shields.io/badge/status-experiment%20concluded-lightgrey.svg)](#what-the-week-showed)

<p align="center">
  <img src="assets/overview.svg" width="760" alt="How it works, in four panels: you type a prompt; Jev guesses which skill fits, for example adr-writer at 93%; in shadow mode the guess is only logged, in inject mode Claude also gets a one-line hint; underneath, Claude still sees every skill and makes the final pick.">
</p>

jev-skill-router is a reference implementation for people building with [TypeSafe](https://typesafe.ai)'s Jev, a model that writes no text and answers typed questions with probabilities. It is a Claude Code hook: on every prompt it asks Jev which installed skill fits and logs the answer. In shadow mode, the default, that is all it does; in inject mode it also gives Claude a one-line hint. It ships with the script that checks that log against what Claude Code actually did next. It is Python 3.10+, standard library only, MIT licensed, version 0.2.0, and needs a paid TypeSafe API key.

I ran it for a week and removed it from my own setup. Of 539 suggestions, 28 were followed by a call of the suggested skill. Inside an agent that picks its own next step, I could not tell what the router changed. What I built on that lesson is [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline), where code owns the loop and Jev only judges ([below](#the-counterpart-jev-research-pipeline)). This README keeps the parts that carry over to other Jev builds, and the reason the whole did not pay off here. The full account is in ["Is There Any Point to This?" Removing the Jev Plugins I Added to Claude Code After One Week](https://dev.to/shimo4228/is-there-any-point-to-this-removing-the-jev-plugins-i-added-to-claude-code-after-one-week-49eh) ([Japanese](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify)), and my other Jev experiments are under [More from the author](#more-from-the-author).

## What the week showed

**A per-prompt hook like this one can add a line to the turn, but it cannot change the skill listing.** Claude Code still shows the model every skill's description, up to 1,536 characters each ([skills docs](https://code.claude.com/docs/en/skills), checked 2026-09-21), and the model still chooses. The router is a second opinion from a weaker judge ([measured against Opus](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj)) to a stronger model that already reads the same descriptions. TypeSafe's [skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion), which this ports, was measured under different conditions: its agent was `claude-haiku-4-5` reading a skill index cut to 60 characters per skill, so a second reader with the full text had more to add.

**Scripted requests went well, real sessions did not.** Six single-intent requests such as "record this decision as an ADR" all got a sensible answer on 0.2.0 (2026-09-21). Then the router ran in shadow mode for a week, from 2026-09-21 to 2026-09-28, on my own roster of 52 to 66 skills, with `jev-1.13.0` and prompts in Japanese:

| Count | Value |
|---|---|
| Decisions | 1,242 |
| Suggestions | 539 |
| Suggested skill called in the same session within 30 minutes | 28 (about 5%) |

After removing it, I read 20 of the unused suggestions, drawn at random. 13 were off target, and at least 6 of those reacted to text written by an agent (a request to a subagent, or a subagent's report), which reaches the hook the same way a message you type does. 5 were near the topic on a turn that needed no skill. In 1, Claude Code read the skill's file instead of calling it. 1 may have been a miss by Claude Code. The script, the options used and the full counts are in [evals/](evals/README.md).

**Why I stopped there.** The 28 mixes three things: Jev's picks, how Claude Code chooses its next step, and how I counted. In an agent that decides its own next move, one added line can change everything after it, and the log cannot separate those three or show whether the router was quietly making things worse. In a pipeline whose steps are fixed in code, swapping one step for a Jev judgment leaves the rest unchanged, so its effect can be read.

## The counterpart: jev-research-pipeline

[jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline) is the Jev build I made after this router's first results, and the one I kept. It is a daily research monitor: plain Python runs the same loop every morning, Jev judges whether each new paper or repository helps answer one of my open questions, and an LLM writes only the notes. Each Jev judgment sits at a fixed point in that loop, so I can see which decisions it made and what changed downstream, which is what this router could never show inside Claude Code. If you are deciding where Jev belongs in your own build, read the two side by side: this repository for the pieces and the measurement, that one for the shape that paid off. The account is in [Moving My Research Pipeline's Judgment Calls from an LLM to Jev](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj) ([Japanese](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)).

## What you can take from it

The question text and thresholds come from TypeSafe's cookbook. What this repository adds is the plumbing around them and the way to measure them. Each row below is one idea you can lift into your own build. Two Jev question types appear: `choice` picks one item from a list, and `noul` answers a yes-or-no question as a probability.

| If you are building | Look at | What it does |
|---|---|---|
| A client for System One, TypeSafe's API for Jev, with no dependencies | [`scripts/jev_client.py`](scripts/jev_client.py) | Uses the standard library only. The key goes to `api.typesafe.ai` and nowhere else except a loopback stub for tests: the host is pinned and redirects are refused. It never retries, because a hook in front of a prompt has a few seconds and a retried timeout spends them twice. |
| A pick from a long list | [`scripts/router.py`](scripts/router.py) | Asks in two requests: a wide `choice` over names and descriptions, then a narrow `choice` over the full text of the top three, plus one `noul` per candidate. A list over 240 items is split to stay under the API's 255-choice cap. |
| A log you can compare across versions | [`scripts/router.py`](scripts/router.py) (`question_hash`), [`scripts/decision_log.py`](scripts/decision_log.py) | Each row carries the model, the router version, and a hash over the question wording and every threshold, so rows written after a change to the questions or thresholds do not pool with old ones. The one exception is the per-candidate fit question, which is not in the hash yet. The prompt is stored only as a hash and a length. |
| A judgment you do not trust yet | [`scripts/route.py`](scripts/route.py) | Shadow mode hands the work to a detached child process and returns at once, so nobody waits on a decision nobody reads. Every failure exits 0. |
| A check against what the agent actually did | [`evals/shadow_join.py`](evals/shadow_join.py) | Joins the decision log with Claude Code's session transcripts, counts suggestions followed by a call, and draws a reproducible sample of unused ones to read by hand. |
| Tests that never call the API | [`tests/`](tests/) | Every Jev answer is a scripted stub, and a golden file freezes the exact output Claude Code parses. |

## How it decides

1. **Wide.** One request ranks the whole roster (your installed skills) by name and whole description with a `choice` question. The same request asks three `noul` questions about the prompt itself: does it act on the user's system, would an expert follow a documented procedure, would prose alone be enough. The third answer is flipped, so that a high score always points to a skill. The mean of the three is the gate: under 0.30, the hook stops and spends no second request.
2. **Narrow.** The top three go back with their whole description and the whole body of their `SKILL.md`. Jev picks one with a `choice`, and answers one `noul` per candidate: does this skill do the specific thing asked? That answer is the candidate's fit. If the best fit is under 0.30, nothing is suggested. Otherwise Jev's pick is named, even when another candidate has the higher fit; the log row then names both.

Nothing is truncated, unlike the cookbook's 60-character index, because ranking on a prefix would rank on less than Claude already sees. The roster is built from your user skills, the skills of enabled plugins, and project skills from the session's working directory up to the git root. Skills marked `disable-model-invocation: true` are left out.

## One decision, as logged

In every mode except `off`, each prompt appends one JSON line to `decisions.jsonl` in the plugin's data directory. This row is from a live call against `jev-1.13.0` in `inject` mode; the prompt, in Japanese, asked to record a design decision as an ADR. `gate` is the mean from step 1, `fits` holds the answers from step 2, and both cleared 0.30, so a skill was named. The row is abridged.

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

In `shadow` mode the row is all that happens. In `inject` mode the turn also gets the block below, with wording copied from the cookbook. When no skill clears the thresholds, nothing is added.

```
<skill_relevance>
Relevant to the current request: adr-writer. Ignore this if it does not fit what the user actually asked for.
</skill_relevance>
```

## Running it yourself

It still installs and runs. Start in shadow mode, and read your own log with [evals/](evals/README.md) before you let it speak.

```
/plugin marketplace add shimo4228/jev-skill-router
/plugin install jev-skill-router@jev-skill-router
```

Claude Code asks for three options when it enables the plugin: a TypeSafe API key ([create one here](https://console.typesafe.ai/keys); stored in your system keychain), the mode (`shadow` by default), and an optional log path. The mode picker needs Claude Code 2.1.271 or newer; on an older build the mode stays `shadow` unless you set the `JEV_ROUTER` environment variable to `inject` or `off`. You can also pass the key as `TYPESAFE_API_KEY`, or keep it in `~/.config/typesafe/api_key`. `JEV_ROUTER=off` turns the hook off for one process, which keeps an unattended script out of it. To wire it up without the plugin system, see [the operating manual](skills/jev-skill-router/SKILL.md#install).

**Cost and latency.** Every routed prompt costs one or two requests, plus one for every further 240 skills. On 0.2.0 with a roster of 52 to 59 skills (2026-09-21), a prompt used about 10,000 input tokens when the gate stopped it and 21,600 to 25,300 when both steps ran. Check [TypeSafe's pricing](https://docs.typesafe.ai/models) for current rates. Shadow mode adds no wait to the turn. `inject` mode waits under a 3-second budget; six live decisions took 0.7 to 1.6 seconds.

### What leaves your machine

Each routed prompt sends to `api.typesafe.ai`: the full prompt text, every roster skill's name and whole description, and, for the top three only, **the whole body of their `SKILL.md`**, including skills in a private project's `.claude/skills/`. The hook does not collect conversation history or tool output, but the prompt it reads can itself be text an agent wrote, such as a subagent's report, which may quote tool results. **A secret pasted into a prompt is sent as typed**; nothing scrubs it.

In a repository you did not write, treat `.claude/skills/`, and anything in that repository it can link to, as part of what a routed prompt can send. That includes a file you added yourself and never committed, such as `.env`. Symlinked skills are followed in your own `~/.claude/skills/` and in plugins, but a project `SKILL.md` is read only if it resolves inside that repository, so a project skill's link to a file elsewhere on your machine is never read or sent. `TYPESAFE_BASE_URL` cannot move your key or prompt to another host; it may only point at a loopback address (`localhost`, `127.0.0.1`, `::1`), for tests and local stubs. The standard proxy variables such as `HTTPS_PROXY` still apply, as they do to any Python HTTPS client.

### Limits

- The thresholds are the cookbook's starting values, measured by the vendor on an English roster with an earlier model version. They are not calibrated for your roster or language.
- Nothing in this repository shows that injecting the suggestion improves anything.
- Built-in skills with no `SKILL.md` on disk, and skills under `--add-dir` directories, cannot be suggested. Prompts starting with `/` and prompts over 4,000 characters are skipped.
- Jev accepts at most 64k tokens per request, and at most 32k for the prompt plus the longest question ([TypeSafe's models page](https://docs.typesafe.ai/models), checked 2026-09-21). Three unusually long `SKILL.md` files, or a large roster, can exceed that; the turn then passes with no suggestion, and the log row carries the reason.

The [operating manual](skills/jev-skill-router/SKILL.md) lists every mode, option, log field and skip condition.

## Related work

- The recipe comes from the [TypeSafe skill suggestion cookbook](https://docs.typesafe.ai/cookbooks/skill_suggestion).
- [DECRUX9812/typesafe-skill-router](https://github.com/DECRUX9812/typesafe-skill-router) implements the same cookbook for Hermes Agent. Two findings come from its documentation: a single question is capped at 255 choices, and the ranking and the per-candidate fit can disagree. No code was copied from it.
- Other routers for Claude Code include [skillranker](https://github.com/Dicklesworthstone/skillranker), a Rust CLI with local history and calibration, and [typesafe-mod](https://github.com/BeLazy167/typesafe-mod), which does the same per-prompt ranking as a function-hooks mod and, like this one, leaves the listing alone.
- To change what the model sees rather than add a line, there are two mechanisms besides a skill's own frontmatter (such as `disable-model-invocation`), and this project uses neither. The official `skillOverrides` setting lists a skill by name and description, by name only, or not at all ([skills docs](https://code.claude.com/docs/en/skills), checked 2026-09-21). Claude Code's early-access function hooks ("mods", [design thread](https://github.com/anthropics/claude-code/issues/91870)) can rewrite the listing before the model sees it. [jev-skill-suggestion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/mods/productivity/jev-skill-suggestion) combines both: it withholds the listing, lets Jev pick at most one skill and attaches its `SKILL.md`. I have not tried it and cannot say whether it works.

## More from the author

I write up each experiment with Jev as an article, in English on Dev.to and in Japanese on Zenn. This repository has two:

- [I Added Jev's Skill Router to Claude Code and Turned Back Just Before Rewriting the Skill Listing](https://dev.to/shimo4228/i-added-jevs-skill-router-to-claude-code-and-turned-back-just-before-rewriting-the-skill-listing-34in) ([Japanese](https://zenn.dev/shimo4228/articles/jev-retrofit-limits)). Building it: what a prompt hook could change, where I stopped, and three things to check before adding a decision model to your own harness.
- ["Is There Any Point to This?" Removing the Jev Plugins I Added to Claude Code After One Week](https://dev.to/shimo4228/is-there-any-point-to-this-removing-the-jev-plugins-i-added-to-claude-code-after-one-week-49eh) ([Japanese](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify)). Running it: a week of this router and a completion guard, why I removed both, and why a judgment model's effect is readable in a fixed pipeline but not in an agent loop.

Where Jev did pay off, and how far it can be pushed:

- [Moving My Research Pipeline's Judgment Calls from an LLM to Jev, a Judgment-Only Model](https://dev.to/shimo4228/moving-my-research-pipelines-judgment-calls-from-an-llm-to-jev-a-judgment-only-model-4ncj) ([Japanese](https://zenn.dev/shimo4228/articles/jev-research-judgment-offload)). The story of the counterpart described above, [jev-research-pipeline](https://github.com/shimo4228/jev-research-pipeline).
- [How Close to Opus Does Jev, a Model That Writes No Text, Get at Skill Selection in 0.3 Seconds?](https://dev.to/shimo4228/how-close-to-opus-does-jev-a-model-that-writes-no-text-get-at-skill-selection-in-03-seconds-1nfj) ([Japanese](https://zenn.dev/shimo4228/articles/jev-vs-opus-skill-selection)). Jev and Claude Opus pick skills for the same 150 situations. Jev agrees with Opus about half as often as Opus agrees with itself, at about 1/560th of the cost.
- [What Does It Take to Reproduce Jev's Decisions Locally?](https://dev.to/shimo4228/what-does-it-take-to-reproduce-jevs-decisions-locally-3i0n) ([Japanese](https://zenn.dev/shimo4228/articles/local-decision-model-conditions)). Four local models replay the same 150 selections, and all four fail, each for a different reason.

The rest of my work, on how agents are built, who is accountable when they fail, and authorship in the AI age, starts at [github.com/shimo4228](https://github.com/shimo4228), where new experiments appear first. The skills I wrote, which made up most of the roster it was measured on, are public in [claude-harness](https://github.com/shimo4228/claude-harness). All articles: [Dev.to](https://dev.to/shimo4228) (English) and [Zenn](https://zenn.dev/shimo4228) (Japanese).

## Provenance

This project is not affiliated with TypeSafe AI. I wrote the code with Claude Code, under my direction. It is checked by an offline test suite (`uv run pytest -q`, no network needed). The paths that carry the key and the prompt were reviewed by automated reviewers (an LLM security-review agent and Claude Code's built-in code review), which found and led to fixes for a key leak on HTTP redirects and for untrusted strings reaching the model's context. No independent human audit has been done.

## Documentation and license

- [Operating manual](skills/jev-skill-router/SKILL.md): every mode, option, log field and skip condition
- [Evals](evals/README.md): the script that joins the log with session transcripts, and my week in numbers
- [Changelog](CHANGELOG.md)
- License: [MIT](LICENSE)
