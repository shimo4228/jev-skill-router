"""The two-call recipe: gate, shortlist, fits, chunking, margin."""

from __future__ import annotations

import pytest
from conftest import ScriptedClient, rerank_response, wide_response

from scripts import router as router_mod
from scripts.roster import Skill

PASSING_GATE = {
    "acts_on_user_system": 0.9,
    "would_follow_documented_procedure": 0.9,
    "prose_suffices": 0.1,
}
FAILING_GATE = {
    "acts_on_user_system": 0.1,
    "would_follow_documented_procedure": 0.1,
    "prose_suffices": 0.9,
}


def skills(*names: str) -> list[Skill]:
    return [
        Skill(
            name=n,
            source="user",
            path=f"/skills/{n}/SKILL.md",
            description=f"{n} full description",
            body=f"# {n}",
        )
        for n in names
    ]


def test_gate_below_threshold_skips_second_call():
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient([wide_response({"alpha": 0.9, "beta": 0.1}, FAILING_GATE)])

    result = router_mod.suggest(client, "just explain monads to me", roster)

    assert result.name is None
    assert len(client.calls) == 1
    assert "gate" in result.reason
    assert result.gate < router_mod.GATE_THRESHOLD


def test_fits_below_threshold_rejects_all():
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response(
                {"alpha": 0.6, "beta": 0.3, "gamma": 0.1},
                {"alpha": 0.10, "beta": 0.05, "gamma": 0.01},
            ),
        ]
    )

    result = router_mod.suggest(client, "post this to Mastodon", roster)

    assert result.name is None
    assert len(client.calls) == 2
    assert "fits" in result.reason


def test_chunked_roster_adds_none_of_these_and_drops_cold_chunks():
    roster = skills(*[f"s{i:03d}" for i in range(500)])
    hot = {f"s{i:03d}": 0.0 for i in range(240)}
    hot.update({"s000": 0.5, "s001": 0.3, "s002": 0.1, router_mod.NONE_OPTION: 0.1})
    cold = {f"s{i:03d}": 0.0 for i in range(240, 480)}
    # s300 outranks the hot chunk's 2nd and 3rd place, but its chunk says nothing here fits.
    cold.update({"s300": 0.4, router_mod.NONE_OPTION: 0.6})
    tail = {f"s{i:03d}": 0.0 for i in range(480, 500)}
    tail.update({"s499": 0.2, router_mod.NONE_OPTION: 0.8})

    client = ScriptedClient(
        [
            wide_response(hot, PASSING_GATE),
            wide_response(cold, PASSING_GATE),
            wide_response(tail, PASSING_GATE),
            rerank_response({"s000": 0.9}, {"s000": 0.8}),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    assert result.chunks == 3
    # Every chunked Choice offers the no-match option.
    for call in client.calls[:3]:
        assert router_mod.NONE_OPTION in call["questions"]["which"]["criteria"]
    # Chunks 2 and 3 said "nothing here fits" (P(none) >= 0.50), so their tops are noise.
    assert result.shortlist == ["s000", "s001", "s002"]
    assert "s300" not in result.shortlist
    # none_of_these never leaks into the shortlist as if it were a skill.
    assert router_mod.NONE_OPTION not in result.shortlist
    assert result.name == "s000"


def test_equal_probability_tie_break_is_deterministic():
    roster = skills("zeta", "alpha", "mu")
    client = ScriptedClient(
        [
            wide_response({"zeta": 0.3, "alpha": 0.3, "mu": 0.3}, PASSING_GATE),
            rerank_response({"alpha": 0.4, "mu": 0.3, "zeta": 0.3}, {"alpha": 0.9}),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    # Ties break on the name, ascending — never on dict insertion order.
    assert result.shortlist == ["alpha", "mu", "zeta"]


def test_fits_margin_is_off_by_default():
    roster = skills("alpha", "beta", "gamma")
    # The Choice picks alpha; the fits nouls clearly prefer beta. Cookbook behaviour keeps
    # the Choice winner; the DECRUX margin rule would override it.
    responses = [
        wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
        rerank_response(
            {"alpha": 0.6, "beta": 0.3, "gamma": 0.1}, {"alpha": 0.50, "beta": 0.85, "gamma": 0.01}
        ),
    ]

    default = router_mod.suggest(ScriptedClient(list(responses)), "do the thing", roster)
    assert router_mod.FITS_MARGIN_DEFAULT is None
    assert default.name == "alpha"

    overridden = router_mod.suggest(
        ScriptedClient(list(responses)), "do the thing", roster, fits_margin=0.15
    )
    assert overridden.name == "beta"


def test_reason_reports_the_fits_of_the_skill_that_was_actually_suggested():
    """Observed live: the row said "best fits 0.63" beside a suggestion whose own fits was
    0.40 — the 0.63 belonged to the candidate that was *not* chosen. A reason that quotes a
    number about a different skill is worse than no number, because it reads as evidence."""
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response(
                {"alpha": 0.6, "beta": 0.3, "gamma": 0.1},
                {"alpha": 0.40, "beta": 0.63, "gamma": 0.01},
            ),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    assert result.name == "alpha"  # the Choice winner still decides; margin stays off
    assert "alpha" in result.reason and "0.40" in result.reason
    assert "beta" in result.reason and "0.63" in result.reason  # the split is named, not hidden


def test_a_fits_key_the_api_invented_cannot_fill_the_reason_line():
    """`fits::<name>` keys come out of the same HTTP body as `choice`, and the reason line
    names the fits leader. Unbounded, a response could write an arbitrary, arbitrarily long
    string into the decision log a later reader parses."""
    roster = skills("alpha", "beta", "gamma")
    injected = "EVIL\n" + "A" * 300
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response(
                {"alpha": 0.6, "beta": 0.3, "gamma": 0.1},
                {"alpha": 0.40, "beta": 0.10, injected: 0.99},
            ),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    assert result.name == "alpha"  # the suggestion is still a name the local roster holds
    assert injected not in result.reason
    assert "\n" not in result.reason
    assert len(result.reason) < 150


def test_reason_when_the_choice_winner_is_also_the_best_fit():
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response(
                {"alpha": 0.6, "beta": 0.3, "gamma": 0.1},
                {"alpha": 0.77, "beta": 0.20, "gamma": 0.01},
            ),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    assert result.name == "alpha"
    assert "winner" in result.reason
    assert "alpha" in result.reason and "0.77" in result.reason
    assert "beta" not in result.reason  # nothing to disclose: the two signals agree


def test_budget_is_wall_clock_across_both_requests(monkeypatch):
    """Three seconds means three seconds total, not three per request."""
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response({"alpha": 0.9}, {"alpha": 0.9}),
        ]
    )
    readings = {"n": 0}

    def clock():
        readings["n"] += 1
        # The deadline is taken first; by the time the wide ranking has answered, the
        # three seconds are long gone.
        return 10.0 if readings["n"] == 1 else 100.0

    monkeypatch.setattr(router_mod.time, "monotonic", clock)

    result = router_mod.suggest(client, "do the thing", roster, budget=3.0)

    assert len(client.calls) == 1  # the wide ranking ate the budget; no second request
    assert result.name is None
    assert "budget" in result.reason
    # Even out of budget a request is never handed a zero or negative socket timeout.
    assert client.calls[0]["timeout"] >= router_mod.MIN_REQUEST_S


def test_question_hash_is_derived_from_the_question_text():
    assert len(router_mod.QUESTION_HASH) == 12
    assert router_mod.QUESTION_HASH == router_mod.question_hash()


@pytest.mark.parametrize("size", [router_mod.MAX_CHOICES + 1, 1000])
def test_chunk_size_above_the_api_cap_is_refused(size):
    with pytest.raises(ValueError, match="255"):
        router_mod.chunk_roster(skills("a"), size)


def test_a_chunked_question_never_exceeds_the_api_cap():
    """Each chunked Choice also carries `none_of_these`, which counts against the 255."""
    roster = skills(*[f"s{i:03d}" for i in range(300)])

    groups = router_mod.chunk_roster(roster, router_mod.MAX_CHOICES)

    assert len(groups) > 1
    for group in groups:
        assert len(group) + 1 <= router_mod.MAX_CHOICES
    # A roster that fits in one question keeps the full width — no option is added there.
    assert len(router_mod.chunk_roster(skills("a", "b"), router_mod.MAX_CHOICES)) == 1


def test_a_winner_that_was_not_on_the_menu_is_dropped():
    """`choice` comes out of an HTTP body; an off-menu value carries no fits noul of its
    own, so it would sail past the fits gate."""
    roster = skills("alpha", "beta", "gamma")
    client = ScriptedClient(
        [
            wide_response({"alpha": 0.5, "beta": 0.3, "gamma": 0.2}, PASSING_GATE),
            rerank_response({"totally-made-up": 0.9}, {"alpha": 0.95, "beta": 0.1, "gamma": 0.1}),
        ]
    )

    result = router_mod.suggest(client, "do the thing", roster)

    assert result.winner is None
    assert result.name == "alpha"  # falls back to the fits leader, which is a candidate
    assert "no Choice winner" in result.reason
