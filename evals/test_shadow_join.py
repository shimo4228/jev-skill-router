"""Tests for the shadow-log join. Every transcript here is synthetic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import shadow_join  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def log_row(
    ts: str,
    session: str,
    suggestion: str | None = None,
    version: str = "0.2.0",
    **extra: object,
) -> dict:
    """A log row in the router's shape: second-resolution time, no prompt text."""
    row: dict = {
        "ts": ts,
        "project": "/somewhere/private/project-a",
        "session": session,
        "mode": "shadow",
        "model": "jev-test",
        "router_version": version,
        "question_hash": "q1",
        "winner": suggestion,
        "suggestion": suggestion,
        "fits": {suggestion: 0.9} if suggestion else {},
        "prompt_chars": 20,
    }
    row.update(extra)
    return row


def skill_event(ts: str, skill: str) -> dict:
    """A transcript event in Claude Code's shape: millisecond-resolution time."""
    return {
        "timestamp": ts,
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": skill}}]},
    }


def user_event(ts: str, text: str, **flags: bool) -> dict:
    return {"timestamp": ts, "type": "user", "message": {"content": text}, **flags}


def make_world(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "decisions.jsonl"
    transcripts = tmp_path / "projects"
    write_jsonl(
        log,
        [
            log_row("2026-09-21T06:00:00Z", "s1", "adr-writer"),
            log_row("2026-09-21T06:10:00Z", "s1", "tdd"),
            log_row("2026-09-21T06:20:00Z", "s1"),
            log_row("2026-09-21T07:00:00Z", "s2", "search-first"),
            log_row("2026-09-21T08:00:00Z", "gone", "tdd", version="0.1.0"),
        ],
    )
    write_jsonl(
        transcripts / "proj-a" / "s1.jsonl",
        [
            user_event("2026-09-21T05:59:58.100Z", "record this decision"),
            skill_event("2026-09-21T06:05:00.123Z", "adr-writer"),
            skill_event("2026-09-21T07:30:00.000Z", "tdd"),
        ],
    )
    write_jsonl(
        transcripts / "proj-a" / "s1" / "subagents" / "agent-1.jsonl",
        [skill_event("2026-09-21T06:12:00.500Z", "tdd")],
    )
    write_jsonl(
        transcripts / "proj-b" / "s2.jsonl",
        [
            user_event(
                "2026-09-21T07:01:00.000Z",
                "<command-name>/search-first</command-name> find a library",
            ),
            skill_event("2026-09-21T07:02:00.000Z", "readme-writer"),
        ],
    )
    return log, transcripts


def test_join_counts_used_and_unused(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    summary, unused = shadow_join.join(shadow_join.read_jsonl(log), transcripts)

    assert summary.rows == 5
    assert summary.suggested == 4
    assert summary.sessions == 3
    assert summary.sessions_without_transcript == 1
    assert summary.suggested_with_transcript == 3
    assert summary.used == 1  # adr-writer, five minutes later
    assert summary.unused == 2  # tdd came 80 minutes later; search-first was never called
    assert {row["suggestion"] for row in unused} == {"tdd", "search-first"}
    assert summary.modes == {"shadow": 5}
    assert summary.judges == {"0.2.0/jev-test/q1": 4, "0.1.0/jev-test/q1": 1}


def test_skill_call_counts_follow_matching_suggestions(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    summary, _ = shadow_join.join(shadow_join.read_jsonl(log), transcripts)

    assert summary.skill_calls == 3
    assert summary.skill_calls_after_matching_suggestion == 1


def test_window_is_inclusive_and_configurable(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    summary, _ = shadow_join.join(shadow_join.read_jsonl(log), transcripts, window_minutes=80)

    assert summary.used == 2  # tdd at exactly +80 minutes now counts


def test_subagent_calls_count_only_when_asked(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    rows = shadow_join.read_jsonl(log)

    main_only, _ = shadow_join.join(rows, transcripts)
    with_subagents, _ = shadow_join.join(rows, transcripts, include_subagents=True)

    assert main_only.used == 1
    assert with_subagents.used == 2  # tdd was called inside a subagent two minutes later
    assert with_subagents.skill_calls == 4
    assert with_subagents.included_subagents is True


def test_slash_commands_count_only_when_asked(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    rows = shadow_join.read_jsonl(log)

    without, _ = shadow_join.join(rows, transcripts)
    with_slash, _ = shadow_join.join(rows, transcripts, count_slash_commands=True)

    assert without.used == 1
    assert with_slash.used == 2
    assert with_slash.counted_slash_commands is True


def test_a_call_before_the_prompt_was_sent_does_not_count(tmp_path: Path) -> None:
    transcripts = tmp_path / "projects"
    write_jsonl(
        transcripts / "p" / "s.jsonl",
        [
            skill_event("2026-09-21T05:59:50.000Z", "tdd"),  # ten seconds before the row
            skill_event("2026-09-21T05:59:59.500Z", "adr-writer"),  # inside elapsed_ms
        ],
    )
    rows = [
        log_row("2026-09-21T06:00:00Z", "s", "tdd", elapsed_ms=800),
        log_row("2026-09-21T06:00:00Z", "s", "adr-writer", elapsed_ms=800),
    ]

    summary, unused = shadow_join.join(rows, transcripts)

    assert summary.used == 1
    assert [row["suggestion"] for row in unused] == ["tdd"]


def test_matching_uses_the_suggestion_not_the_winner(tmp_path: Path) -> None:
    transcripts = tmp_path / "projects"
    write_jsonl(transcripts / "p" / "s.jsonl", [skill_event("2026-09-21T06:01:00.000Z", "tdd")])
    rows = [log_row("2026-09-21T06:00:00Z", "s", "tdd", winner=None)]

    summary, _ = shadow_join.join(rows, transcripts)

    assert summary.used == 1


def test_rows_without_a_readable_time_are_skipped_and_counted(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    rows = shadow_join.read_jsonl(log)
    rows.append({"session": "s1", "suggestion": "tdd"})
    rows.append(log_row("not a time", "s1", "tdd"))
    rows.append(log_row("2026-09-21T06:00:00", "s1", "tdd"))  # no timezone

    summary, _ = shadow_join.join(rows, transcripts)

    assert summary.rows == 5
    assert summary.skipped_rows == 3
    assert summary.suggested == 4


def test_limit_reads_only_the_first_rows(tmp_path: Path) -> None:
    log, _ = make_world(tmp_path)

    assert len(shadow_join.read_jsonl(log, limit=2)) == 2


def test_read_jsonl_skips_broken_lines(tmp_path: Path) -> None:
    path = tmp_path / "broken.jsonl"
    path.write_text('{"a": 1}\nnot json\n[1, 2]\n{"b": 2}\n', encoding="utf-8")

    assert shadow_join.read_jsonl(path) == [{"a": 1}, {"b": 2}]


def test_sample_is_reproducible_and_bounded(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    _, unused = shadow_join.join(shadow_join.read_jsonl(log), transcripts)

    first = shadow_join.sample_unused(unused, 1, seed=7)
    second = shadow_join.sample_unused(list(reversed(unused)), 1, seed=7)

    assert first == second
    assert len(shadow_join.sample_unused(unused, 50, seed=7)) == 2


def test_describe_never_prints_the_project_path_or_the_session(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    row = shadow_join.read_jsonl(log)[0]

    described = shadow_join.describe(row, transcripts, context_chars=0)

    assert described["project"] == "project-a"
    assert described["suggestion"] == "adr-writer"
    assert described["best_fit"] == 0.9
    assert "nearest_user_text" not in described
    assert "session" not in described
    assert "/somewhere" not in json.dumps(described)


def test_context_returns_the_last_typed_message_before_the_row(tmp_path: Path) -> None:
    log, transcripts = make_world(tmp_path)
    row = shadow_join.read_jsonl(log)[0]

    described = shadow_join.describe(row, transcripts, context_chars=6)

    assert described["nearest_user_text"] == "record"


def test_context_skips_text_the_harness_wrote(tmp_path: Path) -> None:
    transcripts = tmp_path / "projects"
    write_jsonl(
        transcripts / "p" / "s.jsonl",
        [
            user_event("2026-09-21T05:59:00.000Z", "what I typed"),
            user_event(
                "2026-09-21T05:59:10.000Z",
                "Base directory for this skill: /somewhere/private",
                isMeta=True,
            ),
            user_event(
                "2026-09-21T05:59:20.000Z", "summary of earlier turns", isCompactSummary=True
            ),
            user_event("2026-09-21T05:59:30.000Z", "a subagent's prompt", isSidechain=True),
            user_event("2026-09-21T05:59:40.000Z", "[Request interrupted by user]"),
            user_event("2026-09-21T05:59:50.000Z", "<system-reminder>note</system-reminder>"),
            user_event("2026-09-21T06:00:30.000Z", "typed after the decision"),
        ],
    )
    row = log_row("2026-09-21T06:00:00Z", "s", "tdd")

    described = shadow_join.describe(row, transcripts, context_chars=80)

    assert described["nearest_user_text"] == "what I typed"


def test_main_prints_a_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log, transcripts = make_world(tmp_path)

    code = shadow_join.main(
        [
            "--log",
            str(log),
            "--transcripts",
            str(transcripts),
            "--sample",
            "2",
            "--seed",
            "3",
            "--context",
            "12",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["summary"]["used"] == 1
    assert len(report["sample"]) == 2
    assert all("nearest_user_text" in row for row in report["sample"])


def test_main_filters_by_version_and_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log, transcripts = make_world(tmp_path)
    base = ["--log", str(log), "--transcripts", str(transcripts)]

    assert shadow_join.main([*base, "--router-version", "0.1.0"]) == 0
    one_version = json.loads(capsys.readouterr().out)["summary"]
    assert shadow_join.main([*base, "--mode", "inject"]) == 0
    other_mode = json.loads(capsys.readouterr().out)["summary"]

    assert one_version["rows"] == 1
    assert one_version["sessions_without_transcript"] == 1
    assert other_mode["rows"] == 0


def test_main_reports_a_missing_log_as_unmeasured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = shadow_join.main(["--log", str(tmp_path / "none.jsonl")])

    assert code == 1
    assert "unmeasured" in capsys.readouterr().err
