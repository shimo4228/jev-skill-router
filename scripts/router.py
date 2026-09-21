"""The two-request recipe: skim the whole roster, then read the top three properly.

Ported from the TypeSafe cookbook "Skill suggestion"
(https://docs.typesafe.ai/cookbooks/skill_suggestion.md, retrieved 2026-09-21). The question
text, the state shape, the two-call structure and both thresholds are the cookbook's; the
chunking, the margin rule and the full-text inputs are not (see below).

The cookbook cuts each description to 60 characters because that is the width Hermes, the
agent it was written against, shows in its own index — the point was to let the cheap pass
read exactly what the agent reads. Claude Code shows the whole description, so this router
sends the whole description, and the whole SKILL.md body for the three candidates the second
request judges. Jev's input budget (64k tokens per request, 32k for ``state`` plus the
longest question — https://docs.typesafe.ai/models.md, retrieved 2026-09-21) is therefore
reachable on a shortlist of unusually long skills. Nothing here measures the request first:
the API is the authority on its own limit, and an over-limit request comes back an error that
the caller's fail-open turns into one logged row and a silent turn.

Every question string and threshold in this module is a *measured input*, not prose: editing
one changes the distribution the decision log records. That is what ``QUESTION_HASH`` is for
— a reader joining old rows to new ones can tell the versions apart instead of averaging
across a silent rewording.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from scripts.roster import Skill

#: Pinned, never read from the environment. An alias would let the answers move under a
#: logged threshold without any change on this side (https://docs.typesafe.ai/models.md).
MODEL = "jev-1.13.0"
#: Bumped whenever the router changes what it asks about, not only how it asks: 0.2.0 sends
#: whole descriptions and whole bodies where 0.1.0 sent 60- and 700-character prefixes, and a
#: reader joining rows across that change would otherwise average two distributions.
ROUTER_VERSION = "0.2.0"

SHORTLIST = 3
GATE_THRESHOLD = 0.30
FITS_THRESHOLD = 0.30
#: Off. The margin rule below is the DECRUX9812/typesafe-skill-router@f150284 observation
#: (MIT, no code copied), not the cookbook's, so it stays dark until the shadow log says how
#: often the Choice and the fits nouls actually disagree here.
FITS_MARGIN_DEFAULT: float | None = None

#: "Too many choices. Must have at most 255 choices." — documented at
#: https://docs.typesafe.ai/api.md, first reported by DECRUX from a 292-skill roster.
MAX_CHOICES = 255
CHUNK_CHOICES = 240
NONE_OPTION = "none_of_these"
#: A chunk this sure that nothing in it fits nominates no candidates: a Choice with no right
#: answer still returns a spread, and its "top three" is noise the second request must reject.
NONE_THRESHOLD = 0.50

#: Total wall clock a caller gets by default. The hook passes its own, much smaller.
DEFAULT_BUDGET_S = 30.0
#: A request with less than this left is not worth starting — it would only spend the
#: caller's remaining budget to time out.
MIN_REQUEST_S = 0.2

CHOICE_INSTRUCTIONS = (
    "Which of these skills, if any, is the right one to load to help with the "
    "user's latest request?"
)
RERANK_INSTRUCTIONS = (
    "Exactly one of these skills is the right one to load for the user's latest "
    "request. Which one? Read what each actually does, not just its name."
)
NONE_CRITERIA = "None of the skills listed here is the right one for this request."
#: Asked about the *request*, never about subject matter: a question about topic cannot
#: separate "explain what a monad is" from a request that needs a skill, since both are
#: software.
GATE_QUESTIONS = {
    "acts_on_user_system": (
        "Is the assistant being asked to act on the user's files, accounts, devices, "
        "or online services, rather than only to explain or advise?"
    ),
    "would_follow_documented_procedure": (
        "Would a careful expert answering this consult a specific documented procedure "
        "or set of commands, rather than answering from general understanding?"
    ),
    "prose_suffices": (
        "Could a knowledgeable generalist fully satisfy this request in prose, with "
        "no tools, no documentation, and no access to the user's files or accounts?"
    ),
}
INVERTED = frozenset({"prose_suffices"})

SUGGESTION_TEMPLATE = (
    "\n\n<skill_relevance>\nRelevant to the current request: {names}. Ignore this if it "
    "does not fit what the user actually asked for.\n</skill_relevance>"
)


class Client(Protocol):
    """The slice of jev_client.JevClient this module needs (and tests substitute)."""

    def ask(
        self,
        state: Mapping[str, str],
        questions: Mapping[str, dict],
        *,
        model: str,
        timeout: float,
    ) -> dict: ...


@dataclass
class Suggestion:
    """One turn's verdict plus everything the decision log wants to record."""

    name: str | None = None
    reason: str = ""
    gate: float = 0.0
    gate_values: dict[str, float] = field(default_factory=dict)
    shortlist: list[str] = field(default_factory=list)
    fits: dict[str, float] = field(default_factory=dict)
    winner: str | None = None
    chunks: int = 1
    usage: dict[str, int] = field(default_factory=dict)


def question_hash() -> str:
    """12 hex chars over every question string and threshold that shapes an answer."""
    parts = [
        CHOICE_INSTRUCTIONS,
        RERANK_INSTRUCTIONS,
        NONE_CRITERIA,
        *(f"{k}={v}" for k, v in sorted(GATE_QUESTIONS.items())),
        f"shortlist={SHORTLIST}",
        f"gate={GATE_THRESHOLD}",
        f"fits={FITS_THRESHOLD}",
        f"none={NONE_THRESHOLD}",
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


QUESTION_HASH = question_hash()


def build_state(request: str) -> dict[str, str]:
    return {"request": request, "recent_context": ""}


def chunk_roster(roster: Sequence[Skill], size: int = CHUNK_CHOICES) -> list[list[Skill]]:
    """Split the roster into question-sized groups.

    A roster that actually splits gets one slot less per chunk: ``rank_wide`` adds
    ``none_of_these`` to every chunked question, and that option counts against the same
    255-choice cap this guard exists to enforce.
    """
    if size > MAX_CHOICES:
        raise ValueError(f"chunk size {size} exceeds the API cap of {MAX_CHOICES} choices")
    if size < 1:
        raise ValueError("chunk size must be positive")
    if len(roster) > size:
        size = min(size, MAX_CHOICES - 1)
    return [list(roster[i : i + size]) for i in range(0, len(roster), size)] or [[]]


def _ranked(answer: Mapping[str, Any]) -> list[tuple[str, float]]:
    """Probabilities, highest first, ties broken on the name so the order is reproducible."""
    probabilities = answer.get("probabilities") or {}
    pairs = [(str(k), float(v)) for k, v in probabilities.items()]
    return sorted(pairs, key=lambda kv: (-kv[1], kv[0]))


def _time_left(deadline: float | None) -> float:
    """Seconds still allowed. ``None`` means the caller set no wall clock."""
    if deadline is None:
        return DEFAULT_BUDGET_S
    return deadline - time.monotonic()


def _add_usage(total: dict[str, int], response: Mapping[str, Any]) -> None:
    usage = response.get("usage") or {}
    for key in ("input_tokens", "output_tokens"):
        total[key] = total.get(key, 0) + int(usage.get(key) or 0)
    total["calls"] = total.get("calls", 0) + 1


def rank_wide(
    client: Client,
    request: str,
    roster: Sequence[Skill],
    *,
    shortlist: int = SHORTLIST,
    chunk: int = CHUNK_CHOICES,
    deadline: float | None = None,
    usage: dict[str, int] | None = None,
) -> dict:
    """Request 1: rank the whole roster on full descriptions, and score the request for
    whether a skill applies at all.

    Over the 255-choice cap the roster is asked in chunks. Each chunk then also offers
    ``none_of_these``, and a chunk whose P(none) reaches ``NONE_THRESHOLD`` nominates
    nothing — except the chunk holding the single highest-probability skill, so a run always
    produces a shortlist for the second request to judge on real text.

    ``deadline`` is a wall clock shared by every request, not a per-request timeout: a
    caller who allows three seconds means three seconds total, and a chunked roster would
    otherwise multiply that by the number of chunks. Chunks that no longer fit are dropped
    and ``chunks`` reports how many were actually asked.
    """
    groups = chunk_roster(roster, chunk)
    chunked = len(groups) > 1
    usage = usage if usage is not None else {}
    gate_values: dict[str, float] = {}
    per_chunk: list[list[tuple[str, float]]] = []
    none_pressure: list[float] = []

    for index, group in enumerate(groups):
        left = _time_left(deadline)
        if left < MIN_REQUEST_S and index > 0:
            break  # out of budget: rank on the chunks already answered
        criteria = {skill.name: skill.description for skill in group}
        if chunked:
            criteria[NONE_OPTION] = NONE_CRITERIA
        questions: dict[str, dict] = {
            "which": {
                "type": "choice",
                "instructions": CHOICE_INSTRUCTIONS,
                "criteria": criteria,
            }
        }
        if index == 0:  # the gate is about the request, so it rides on the first chunk only
            for key, text in GATE_QUESTIONS.items():
                questions[f"gate::{key}"] = {"type": "noul", "instructions": text}

        response = client.ask(
            build_state(request), questions, model=MODEL, timeout=max(left, MIN_REQUEST_S)
        )
        _add_usage(usage, response)
        answers = response.get("answers") or {}
        ranked = _ranked(answers.get("which") or {})
        none_pressure.append(dict(ranked).get(NONE_OPTION, 0.0))
        per_chunk.append([pair for pair in ranked if pair[0] != NONE_OPTION])
        for key, answer in answers.items():
            if key.startswith("gate::"):
                gate_values[key[len("gate::") :]] = float(answer.get("noul") or 0.0)

    oriented = [(1.0 - v) if k in INVERTED else v for k, v in gate_values.items()]
    best_chunk = max(
        range(len(per_chunk)), key=lambda i: per_chunk[i][0][1] if per_chunk[i] else -1.0
    )
    nominated: list[tuple[str, float]] = []
    for index, ranked in enumerate(per_chunk):
        if index != best_chunk and none_pressure[index] >= NONE_THRESHOLD:
            continue
        nominated.extend(ranked[:shortlist])
    nominated.sort(key=lambda kv: (-kv[1], kv[0]))
    return {
        "ranked": nominated[:shortlist],
        "gate": (sum(oriented) / len(oriented)) if oriented else 0.0,
        "values": gate_values,
        "chunks": len(per_chunk),
    }


def rerank(
    client: Client,
    request: str,
    candidates: Sequence[Skill],
    *,
    timeout: float = DEFAULT_BUDGET_S,
    usage: dict[str, int] | None = None,
) -> dict:
    """Request 2: the same Choice over the shortlist — each candidate's full description and
    full SKILL.md body — plus one absolute noul per candidate.

    Each ``fits`` noul is answered on its own, so they can all come back low and the whole
    shortlist can be dropped — which is the only way this recipe stays quiet on a turn where
    the roster genuinely has nothing.
    """
    criteria = {skill.name: f"{skill.description} — {skill.body}" for skill in candidates}
    questions: dict[str, dict] = {
        "which": {"type": "choice", "instructions": RERANK_INSTRUCTIONS, "criteria": criteria}
    }
    for skill in candidates:
        questions[f"fits::{skill.name}"] = {
            "type": "noul",
            "instructions": (
                f"Does the skill '{skill.name}' do the specific thing the user's request "
                f"asks for? It is described as: {skill.description}"
            ),
        }
    response = client.ask(build_state(request), questions, model=MODEL, timeout=timeout)
    if usage is not None:
        _add_usage(usage, response)
    answers = response.get("answers") or {}
    which = answers.get("which") or {}
    fits = {
        key[len("fits::") :]: float(answer.get("noul") or 0.0)
        for key, answer in answers.items()
        if key.startswith("fits::")
    }
    # `choice` is a field of an HTTP response body, and an off-menu value would carry no
    # `fits` noul of its own — so it would sail past the fits gate, which only ever reads
    # the best one. Anything not on the menu we sent is dropped here; `_decide` then falls
    # back to the fits leader, which is a candidate by construction.
    winner = which.get("choice")
    if winner not in {skill.name for skill in candidates}:
        winner = None
    return {"winner": winner, "fits": fits}


def _named(name: str) -> str:
    """A fits key as it may be written into the decision log.

    The ``fits::`` keys are fields of an HTTP response body and are not held to the menu that
    was sent — only ``choice`` is. The fits leader's name is printed into ``reason``, so a
    response could otherwise put an arbitrary, arbitrarily long string into a file a later
    reader parses. Bounded and repr'd, the same way ``route.py`` handles an off-menu
    suggestion.
    """
    return repr(name[:60])


def _decide(
    winner: str | None, fits: Mapping[str, float], threshold: float, margin: float | None
) -> tuple[str | None, str]:
    """Turn the second request's answers into at most one name, plus why.

    With ``margin`` unset this is the cookbook exactly: the best fits noul opens the gate and
    the Choice settles which skill. With a margin, the fits leader may override the Choice —
    but only when it clears the bar *and* leads by that much, because a smaller gap is two
    signals disagreeing and a wrong name costs more than silence.
    """
    if not fits:
        return None, "no fits answers returned"
    ranked = sorted(fits.items(), key=lambda kv: (-kv[1], kv[0]))
    best_name, best_fits = ranked[0]
    if best_fits < threshold:
        return (
            None,
            f"best fits {_named(best_name)} {best_fits:.2f} < {threshold:.2f}: nothing fits",
        )
    if winner is None:
        return best_name, f"no Choice winner; fits leader {_named(best_name)} {best_fits:.2f}"
    winner_fits = fits.get(winner, 0.0)
    if margin is not None and best_name != winner and best_fits - winner_fits >= margin:
        return best_name, (
            f"fits override: {_named(best_name)} {best_fits:.2f} leads winner {winner} "
            f"{winner_fits:.2f} by {best_fits - winner_fits:.2f}"
        )
    # The number in the reason is the *suggested* skill's own fits. Quoting the best fits here
    # put a figure belonging to a candidate that lost beside the name of the one that won
    # (observed live: winner at 0.40, reason reading 0.63), which reads as evidence for a
    # choice it had nothing to do with. When the two signals split, both are named.
    if best_name == winner:
        return winner, f"shortlist winner {winner} (fits {winner_fits:.2f})"
    return winner, (
        f"choice winner {winner} (fits {winner_fits:.2f}); "
        f"best fits {_named(best_name)} {best_fits:.2f}"
    )


def suggest(
    client: Client,
    request: str,
    roster: Sequence[Skill],
    *,
    shortlist: int = SHORTLIST,
    gate_threshold: float = GATE_THRESHOLD,
    fits_threshold: float = FITS_THRESHOLD,
    fits_margin: float | None = FITS_MARGIN_DEFAULT,
    chunk: int = CHUNK_CHOICES,
    budget: float = DEFAULT_BUDGET_S,
) -> Suggestion:
    """At most one skill name for a request. Either step may come back empty-handed.

    ``budget`` is wall clock for the whole recipe, both requests included. The caller in
    front of a human prompt has one number in mind, and a per-request timeout would quietly
    let two requests spend it twice.
    """
    result = Suggestion()
    if not roster:
        result.reason = "empty roster"
        return result

    deadline = time.monotonic() + budget
    usage: dict[str, int] = {}
    wide = rank_wide(
        client, request, roster, shortlist=shortlist, chunk=chunk, deadline=deadline, usage=usage
    )
    result.usage = usage
    result.gate = wide["gate"]
    result.gate_values = wide["values"]
    result.chunks = wide["chunks"]
    if result.gate < gate_threshold:
        result.reason = f"gate {result.gate:.2f} < {gate_threshold:.2f}: no skill needed"
        return result

    by_name = {skill.name: skill for skill in roster}
    candidates = [by_name[name] for name, _ in wide["ranked"] if name in by_name]
    result.shortlist = [skill.name for skill in candidates]
    if not candidates:
        result.reason = "no candidates survived the wide ranking"
        return result

    left = _time_left(deadline)
    if left < MIN_REQUEST_S:
        result.reason = "budget spent on the wide ranking; not starting the second request"
        return result

    second = rerank(client, request, candidates, timeout=left, usage=usage)
    result.fits = second["fits"]
    result.winner = second["winner"]
    result.name, result.reason = _decide(
        second["winner"], second["fits"], fits_threshold, fits_margin
    )
    return result


def suggestion_block(name: str) -> str:
    """The one line that goes into the system prompt, verbatim from the cookbook.

    It says the suggestion can be ignored on purpose: pushing harder wins compliance on wrong
    suggestions too, and a wrong one is worse than none.
    """
    return SUGGESTION_TEMPLATE.format(names=name)
