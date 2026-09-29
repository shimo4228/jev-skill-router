"""Join the router's shadow log with Claude Code session transcripts.

The router records what Jev picked. It does not record what the session did next. This
reader joins the two by ``session`` and time and prints two counts, suggested and used,
and suggested but unused, plus how many Skill calls followed a matching suggestion.
Whether an unused suggestion was sensible is not something a count can say: draw a sample
with ``--sample`` and read it.

Everything is read from local files and nothing is sent anywhere. The summary holds counts
only. ``--sample`` prints rows from the log, which never contains prompt text; ``--context``
adds the start of the nearest message you typed, taken from your own transcript, for
reading on your own machine.

Stdlib only, so it runs wherever the router runs.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_LOG = Path.home() / ".claude/plugins/data/jev-skill-router-jev-skill-router/decisions.jsonl"
DEFAULT_TRANSCRIPTS = Path.home() / ".claude/projects"
DEFAULT_WINDOW_MINUTES = 30

#: Claude Code writes a typed slash command into the user message as this tag.
SLASH_COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
#: User events that carry these flags were written by the harness, not typed.
NOT_TYPED = ("isMeta", "isCompactSummary", "isSidechain")
INTERRUPTED = "[Request interrupted"

SkillCall = tuple[datetime, str]


@dataclass
class Summary:
    """Counts only. Nothing here can reconstruct a prompt."""

    rows: int = 0
    skipped_rows: int = 0
    suggested: int = 0
    sessions: int = 0
    sessions_without_transcript: int = 0
    suggested_with_transcript: int = 0
    used: int = 0
    unused: int = 0
    skill_calls: int = 0
    skill_calls_after_matching_suggestion: int = 0
    window_minutes: int = DEFAULT_WINDOW_MINUTES
    counted_slash_commands: bool = False
    included_subagents: bool = False
    modes: dict[str, int] = field(default_factory=dict)
    #: Rows per judge. Rows that differ here come from a different judge: read them apart.
    judges: dict[str, int] = field(default_factory=dict)


def parse_ts(value: object) -> datetime | None:
    """A timezone-aware time, or None when the value is not a readable timestamp."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Read JSONL rows in file order, skipping lines that are not JSON objects."""
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if limit is not None and len(rows) >= limit:
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def find_transcript(root: Path, session: str) -> Path | None:
    matches = sorted(root.glob(f"*/{session}.jsonl"))
    return matches[0] if matches else None


def find_subagent_transcripts(root: Path, session: str) -> list[Path]:
    """Transcripts of the subagents a session started, stored beside the session's own."""
    return sorted(root.glob(f"*/{session}/subagents/*.jsonl"))


def _content_items(event: dict[str, Any]) -> list[dict[str, Any]]:
    message = event.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    return []


def _event_text(event: dict[str, Any]) -> str:
    return " ".join(
        str(item.get("text", "")) for item in _content_items(event) if item.get("type") == "text"
    )


def skill_calls(
    events: list[dict[str, Any]], count_slash_commands: bool = False
) -> list[SkillCall]:
    """Every Skill tool call in a transcript, as (time, skill name).

    With ``count_slash_commands``, a slash command typed by the user counts as a call of the
    skill with that name.
    """
    calls: list[SkillCall] = []
    for event in events:
        when = parse_ts(event.get("timestamp"))
        if when is None:
            continue
        for item in _content_items(event):
            if item.get("type") == "tool_use" and item.get("name") == "Skill":
                skill = (item.get("input") or {}).get("skill")
                if isinstance(skill, str):
                    calls.append((when, skill))
        if count_slash_commands and event.get("type") == "user":
            calls.extend((when, name) for name in SLASH_COMMAND.findall(_event_text(event)))
    return calls


def window_of(row: dict[str, Any], window: timedelta) -> tuple[datetime, datetime] | None:
    """The span in which a call counts as following this row's suggestion.

    A row is written after Jev answers, so the span starts ``elapsed_ms`` before ``ts``:
    that is when the prompt was sent.
    """
    logged = parse_ts(row.get("ts"))
    if logged is None:
        return None
    elapsed = row.get("elapsed_ms")
    sent = logged - timedelta(milliseconds=elapsed if isinstance(elapsed, (int, float)) else 0)
    return sent, logged + window


def followed(row: dict[str, Any], call: SkillCall, window: timedelta) -> bool:
    """True when ``call`` names the skill this row suggested and falls inside its window."""
    span = window_of(row, window)
    when, name = call
    return span is not None and name == row.get("suggestion") and span[0] <= when <= span[1]


def judge_of(row: dict[str, Any]) -> str:
    """The three fields that identify which judge produced a row."""
    return "/".join(str(row.get(key)) for key in ("router_version", "model", "question_hash"))


def session_calls(
    transcripts: Path, session: str, count_slash_commands: bool, include_subagents: bool
) -> list[SkillCall] | None:
    """Skill calls of one session, or None when the session left no transcript."""
    path = find_transcript(transcripts, session)
    if path is None:
        return None
    paths = [path]
    if include_subagents:
        paths += find_subagent_transcripts(transcripts, session)
    calls: list[SkillCall] = []
    for item in paths:
        calls += skill_calls(read_jsonl(item), count_slash_commands)
    return calls


def join(
    rows: list[dict[str, Any]],
    transcripts: Path,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    count_slash_commands: bool = False,
    include_subagents: bool = False,
) -> tuple[Summary, list[dict[str, Any]]]:
    """Join log rows with transcripts. Returns the summary and the unused suggestions."""
    window = timedelta(minutes=window_minutes)
    summary = Summary(
        window_minutes=window_minutes,
        counted_slash_commands=count_slash_commands,
        included_subagents=include_subagents,
    )
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if parse_ts(row.get("ts")) is None:
            summary.skipped_rows += 1
            continue
        summary.rows += 1
        mode = str(row.get("mode"))
        summary.modes[mode] = summary.modes.get(mode, 0) + 1
        judge = judge_of(row)
        summary.judges[judge] = summary.judges.get(judge, 0) + 1
        by_session.setdefault(str(row.get("session")), []).append(row)
    summary.sessions = len(by_session)

    unused: list[dict[str, Any]] = []
    for session, session_rows in by_session.items():
        suggestions = [row for row in session_rows if row.get("suggestion")]
        summary.suggested += len(suggestions)
        calls = session_calls(transcripts, session, count_slash_commands, include_subagents)
        if calls is None:
            summary.sessions_without_transcript += 1
            continue
        summary.suggested_with_transcript += len(suggestions)
        summary.skill_calls += len(calls)
        summary.skill_calls_after_matching_suggestion += sum(
            any(followed(row, call, window) for row in suggestions) for call in calls
        )
        for row in suggestions:
            if any(followed(row, call, window) for call in calls):
                summary.used += 1
            else:
                unused.append(row)
    summary.unused = len(unused)
    return summary, unused


def sample_unused(unused: list[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """A reproducible random sample of unused suggestions, for reading one by one."""
    ordered = sorted(unused, key=lambda row: (str(row.get("ts")), str(row.get("session"))))
    return random.Random(seed).sample(ordered, min(size, len(ordered)))


def is_typed(event: dict[str, Any]) -> bool:
    """True for a user event that holds text a person typed."""
    if event.get("type") != "user" or any(event.get(flag) for flag in NOT_TYPED):
        return False
    text = _event_text(event).strip()
    return bool(text) and not text.startswith("<") and not text.startswith(INTERRUPTED)


def nearest_user_text(events: list[dict[str, Any]], when: datetime, chars: int) -> str:
    """The start of the last message a person typed at or before ``when``.

    This is a guess at what was judged. Text written by an agent (a request to a subagent,
    a subagent's report) passes through the same hook, and the router may have judged that
    text rather than the message returned here.
    """
    text = ""
    for event in events:
        stamp = parse_ts(event.get("timestamp"))
        if stamp is None or not is_typed(event):
            continue
        if stamp > when:
            break
        text = _event_text(event).strip()
    return text[:chars]


def describe(row: dict[str, Any], transcripts: Path, context_chars: int) -> dict[str, Any]:
    raw_fits = row.get("fits")
    fits: dict[str, float] = raw_fits if isinstance(raw_fits, dict) else {}
    out: dict[str, Any] = {
        "ts": row.get("ts"),
        "project": Path(str(row.get("project", ""))).name,
        "suggestion": row.get("suggestion"),
        "winner": row.get("winner"),
        "best_fit": max(fits.values(), default=None),
        "prompt_chars": row.get("prompt_chars"),
    }
    when = parse_ts(row.get("ts"))
    if context_chars > 0 and when is not None:
        path = find_transcript(transcripts, str(row.get("session")))
        events = read_jsonl(path) if path else []
        out["nearest_user_text"] = nearest_user_text(events, when, context_chars)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="decisions.jsonl")
    parser.add_argument("--transcripts", type=Path, default=DEFAULT_TRANSCRIPTS)
    parser.add_argument("--limit", type=int, default=None, help="read only the first N rows")
    parser.add_argument("--router-version", default=None, help="keep only rows of this version")
    parser.add_argument("--mode", default=None, help="keep only rows of this mode (shadow, inject)")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW_MINUTES, help="minutes")
    parser.add_argument("--count-slash-commands", action="store_true")
    parser.add_argument(
        "--include-subagents",
        action="store_true",
        help="also count Skill calls made inside the session's subagents",
    )
    parser.add_argument("--sample", type=int, default=0, help="print N unused suggestions")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--context",
        type=int,
        default=0,
        help=(
            "with --sample, print this many characters of the nearest message you typed. "
            "This is text from your own transcripts: check it before you share the output"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.log.exists():
        print(f"no log at {args.log}: unmeasured, not zero", file=sys.stderr)
        return 1
    rows = read_jsonl(args.log, args.limit)
    if args.router_version is not None:
        rows = [row for row in rows if row.get("router_version") == args.router_version]
    if args.mode is not None:
        rows = [row for row in rows if row.get("mode") == args.mode]
    summary, unused = join(
        rows, args.transcripts, args.window, args.count_slash_commands, args.include_subagents
    )
    report: dict[str, Any] = {"summary": asdict(summary)}
    if args.sample > 0:
        report["sample"] = [
            describe(row, args.transcripts, args.context)
            for row in sample_unused(unused, args.sample, args.seed)
        ]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
