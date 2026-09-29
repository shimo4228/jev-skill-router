# Evals: reading a week of shadow log

The router logs what Jev picked. It does not log what the session did next. `shadow_join.py` joins the two, so you can see how often a suggested skill was actually called.

The author ran the router in shadow mode for a week, read the join, and removed the router from their own setup. The story is in the article [「これ意味あるかな？」Claude Codeに入れたJevのプラグインを1週間で外すまで](https://zenn.dev/shimo4228/articles/jev-guard-blind-to-local-verify) (Japanese, on Zenn). This page holds the method and the numbers behind it.

## Run it on your own log

```bash
python3 evals/shadow_join.py
```

It needs Python 3.10 or later and nothing else. It reads two places on your machine and sends nothing anywhere:

- the router's log, `~/.claude/plugins/data/jev-skill-router-jev-skill-router/decisions.jsonl`
- Claude Code's session transcripts, `~/.claude/projects/*/<session>.jsonl`

| Option | What it does |
|---|---|
| `--log PATH`, `--transcripts DIR` | Read from somewhere else |
| `--limit N` | Read only the first N rows of the log |
| `--router-version V` | Keep only rows written by that router version |
| `--mode M` | Keep only rows of that mode (`shadow` or `inject`) |
| `--window MINUTES` | How long after a suggestion a call still counts (default 30) |
| `--include-subagents` | Also count Skill calls made inside the session's subagents |
| `--count-slash-commands` | Count a slash command you typed as a call of that skill |
| `--sample N --seed S` | Print N unused suggestions, chosen at random, to read one by one |
| `--context CHARS` | With `--sample`, print the start of the nearest message you typed |

The output is JSON. `summary` holds counts only. `sample` rows come from the log, which never stores prompt text. They show the project's folder name, not its path, and no session id. `--context` prints text from your own transcripts, so check it before you paste the output anywhere.

## What the counts mean

| Field | Meaning |
|---|---|
| `rows` | Decisions read from the log |
| `skipped_rows` | Rows left out because their time could not be read |
| `suggested` | Rows where the router named a skill |
| `sessions`, `sessions_without_transcript` | Sessions in the log, and how many left no transcript |
| `suggested_with_transcript` | Suggestions that can be checked |
| `used` | The session called the suggested skill within the window |
| `unused` | It did not |
| `skill_calls` | Every Skill tool call in those sessions |
| `skill_calls_after_matching_suggestion` | Calls that came within the window after a suggestion of the same skill |
| `judges` | Rows per `router_version/model/question_hash` |
| `modes` | Rows per mode |

The window opens when the prompt was sent (`ts` minus `elapsed_ms`) and closes `--window` minutes after `ts`.

Rows that differ in `judges` come from a different judge, and rows in `inject` mode come from sessions that saw the suggestion. Read them apart, with `--router-version` and `--mode`.

The script counts. It cannot tell whether an unused suggestion was sensible. For that, draw a sample and read it.

## The author's week

The log covers 2026-09-21 to 2026-09-28, with `jev-1.13.0`, a roster of 52 to 66 skills, and prompts in Japanese. The first 1,242 rows are the week up to the moment the router was turned off. All of them are in shadow mode. The numbers below were produced on 2026-09-29 with:

```bash
python3 evals/shadow_join.py --limit 1242 --include-subagents
```

| Count | Value |
|---|---|
| Decisions | 1,242 |
| Suggestions | 539 |
| Sessions | 71, of which 10 left no transcript |
| Suggestions that can be checked | 534 |
| Suggested skill called within 30 minutes | 28 |
| The same, counting the main session only (no `--include-subagents`) | 26 |
| Skill calls in those sessions | 138, of which 26 followed a matching suggestion |

The article reports 28 of 539, about 5%. Counting calls inside subagents gives that number. Counting the main session alone gives 26. With `--count-slash-commands` added, the two become 29 and 27.

The 10 sessions without a transcript hold one decision each, and 5 of the 539 suggestions. Eight of them ran on one morning, a few minutes apart, which fits a scheduled job that runs Claude Code without saving its session. Their suggestions cannot be checked, so they are in `suggested` and in neither `used` nor `unused`.

The 1,242 rows pool two router versions: 1,223 rows from 0.2.0 and 19 from 0.1.0, which ranked on truncated text. For 0.2.0 alone the script gives 526 suggestions and the same 28 calls.

Input per decision averaged about 22,000 tokens over the 1,030 rows that recorded usage.

## Reading 20 unused suggestions

A count cannot say whether an unused suggestion was a miss by Claude Code or a wrong pick by Jev. After removing the router, the author drew 20 unused suggestions and read each conversation. The draw was made on the main sessions alone, from 508 unused suggestions:

```bash
python3 evals/shadow_join.py --limit 1242 --sample 20 --seed 20260929
```

This reproduces the draw for as long as the same transcripts are on disk.

| Reading | Count |
|---|---|
| Off target | 13 |
| Near the topic, but the turn did not need a skill | 5 |
| Claude Code read the skill's file directly instead of calling it | 1 |
| Possibly a miss by Claude Code | 1 |

At least 6 of the 13 off-target picks were made on text written by an agent: a request sent to a subagent, or a subagent's report. Inside Claude Code that text passes through the same hook as a message you type.

Twenty rows give a rough proportion and no more. The conversations themselves are not published.

## Limits

- "Used" means the Skill tool was called with the suggested name, in the same session, within the window. A skill that Claude Code read as a file is counted as unused. Without `--include-subagents`, so is a call made inside a subagent.
- `--context` returns the last message you typed before the decision. The router may have judged different text (see above), so treat it as a guess.
- A session that left no transcript cannot be checked.
- The numbers above come from one person's setup in one week. They describe that setup.

## Tests

```bash
uv run pytest evals -q --no-cov
```

Every transcript in the tests is synthetic.
