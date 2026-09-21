"""One JSONL line per routed turn — the registry the shadow phase exists to fill.

This layer only appends. Read-back, aggregation and rendering belong to whoever reads the
file later; a ledger that grows its own state machine grows its own bugs.

What is deliberately *not* in a row: the prompt text and the API key. A row carries
``prompt_sha`` and ``prompt_chars`` so a reader can tell two turns apart and see how long
they were, and nothing that reconstructs what was typed. Outcome is joined by the reader:
``session`` + ``ts`` against Claude Code's own skill-usage log.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Only the owner reads a decision log.
LOG_MODE = 0o600
#: ...and the directory holding it is created just as closed. A plugin's ``CLAUDE_PLUGIN_DATA``
#: may not exist yet, so this layer is the one that creates it. ``mkdir`` applies this mode to
#: the final component only — any intermediate directories it has to create still land at the
#: umask default — so this closes the directory the rows sit in, not the whole path to it.
DIR_MODE = 0o700


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build_record(
    *,
    project: str,
    session: str,
    mode: str,
    model: str,
    router_version: str,
    question_hash: str,
    roster_hash: str,
    n_skills: int,
    n_by_source: dict[str, int],
    prompt: str,
    elapsed_ms: int,
    suggestion: str | None = None,
    reason: str = "",
    gate: float = 0.0,
    gate_values: dict[str, float] | None = None,
    shortlist: list[str] | None = None,
    fits: dict[str, float] | None = None,
    winner: str | None = None,
    chunks: int = 1,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """One registry row. Field order is the schema's reading order, not accidental."""
    return {
        "ts": utc_now(),
        "project": project,
        "session": session,
        "mode": mode,
        "model": model,
        "router_version": router_version,
        "question_hash": question_hash,
        "roster_hash": roster_hash,
        "n_skills": n_skills,
        "n_by_source": dict(n_by_source),
        "prompt_sha": digest(prompt),
        "prompt_chars": len(prompt),
        "gate": round(gate, 4),
        "gate_values": {k: round(v, 4) for k, v in (gate_values or {}).items()},
        "shortlist": list(shortlist or []),
        "fits": {k: round(v, 4) for k, v in (fits or {}).items()},
        "winner": winner,
        "suggestion": suggestion,
        "reason": reason,
        "chunks": chunks,
        "usage": dict(usage or {}),
        "elapsed_ms": elapsed_ms,
    }


def append(path: Path, record: dict[str, Any]) -> bool:
    """Append one line. Returns False when the row was dropped; never raises.

    A symlinked log *file* is refused, twice over — the check and ``O_NOFOLLOW``, which also
    closes the gap between them. This runs unattended on every prompt, so a single planted
    link would otherwise be an append primitive against any file the user can write,
    settings.json included. The guard stops at the final component: a symlinked parent
    directory is still followed by ``mkdir``, which needs write access to the log's own
    directory to plant and is the same exposure ``hooks/log-skill-usage.sh`` carries.
    """
    try:
        if path.is_symlink():
            return False
        path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, LOG_MODE)
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        return False
    return True
