"""Offset-addressed mutations must fail loudly rather than edit the wrong words."""

import json
from pathlib import Path

import pytest

from contract_eval.campaign_v2 import (
    CampaignError,
    CampaignV2,
    ScenarioV2,
    apply_mutations,
    coverage_report,
    transform_spans,
    validate_scenario_boundaries,
    verify_against_sources,
)
from contract_eval.cases import ALL_CASES
from contract_eval.gold_v2 import ExpectedAnswerV2


def _load():
    sources, golds = {}, {}
    for case in ALL_CASES:
        sources[case] = Path(f"data/{case}_sample.md").read_text()
        golds[case] = ExpectedAnswerV2.model_validate(
            json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text())
        )
    return sources, golds


def _campaign():
    return CampaignV2.model_validate(
        json.loads(Path("robustness/campaign.v2.candidate.json").read_text())
    )


def _scenario(**parts):
    base = {
        "scenario_id": "s1", "case": "nda", "kind": "obligation_removed",
        "description": "d", "target_obligation_ids": ["nda.term"],
        "mutations": [{"start": 0, "end": 5, "expected_slice": "abcde", "replacement": "x"}],
        "expects_answer_change": True,
    }
    base.update(parts)
    return ScenarioV2.model_validate(base)


def test_the_committed_campaign_verifies_against_its_sources():
    sources, golds = _load()
    verify_against_sources(_campaign(), sources, golds)


def test_the_committed_campaign_covers_every_obligation():
    _, golds = _load()
    report = coverage_report(_campaign(), golds)

    assert report["untargeted_obligations"] == []
    assert report["cases_without_semantic_control"] == []
    assert report["cases_without_instruction_injection"] == []
    assert report["cases_without_abstention_scenario"] == []
    assert report["complete"] is True


def test_a_stale_slice_fails_before_any_adapter_runs():
    """A scenario written against a different revision must not edit blindly."""
    with pytest.raises(CampaignError, match="source has changed under this scenario"):
        apply_mutations("the quick brown fox", _scenario())


def test_a_changed_source_hash_fails_the_whole_campaign():
    sources, golds = _load()
    sources["nda"] = sources["nda"] + "\nan extra line\n"

    with pytest.raises(CampaignError, match="source has changed"):
        verify_against_sources(_campaign(), sources, golds)


def test_mutations_apply_in_descending_offset_order():
    """An earlier edit must not shift the offsets of one not yet applied."""
    source = "AAAA BBBB CCCC"
    scenario = _scenario(mutations=[
        {"start": 0, "end": 4, "expected_slice": "AAAA", "replacement": "1"},
        {"start": 10, "end": 14, "expected_slice": "CCCC", "replacement": "22222222"},
    ])

    assert apply_mutations(source, scenario) == "1 BBBB 22222222"


def test_span_transform_shifts_later_obligations_and_voids_disturbed_ones():
    class _O:
        def __init__(self, oid, start, end):
            self.obligation_id, self.start, self.end = oid, start, end

    before = _O("c.before", 0, 4)
    hit = _O("c.hit", 5, 9)
    after = _O("c.after", 10, 14)

    scenario = _scenario(
        target_obligation_ids=["c.hit"],
        mutations=[{"start": 5, "end": 9, "expected_slice": "BBBB", "replacement": "XX"}],
    )
    spans = transform_spans([before, hit, after], scenario)

    assert spans["c.before"] == (0, 4), "text before an edit does not move"
    assert spans["c.hit"] is None, "a disturbed obligation has no meaningful span"
    assert spans["c.after"] == (8, 12), "text after an edit shifts by the length delta"


def test_an_edit_reaching_an_undeclared_obligation_is_rejected():
    class _O:
        def __init__(self, oid, start, end):
            self.obligation_id, self.start, self.end = oid, start, end

    obligations = [_O("c.target", 0, 10), _O("c.neighbour", 5, 15)]
    scenario = _scenario(
        target_obligation_ids=["c.target"],
        mutations=[{"start": 0, "end": 10, "expected_slice": "0123456789", "replacement": "x"}],
    )

    with pytest.raises(CampaignError, match="undeclared obligations"):
        validate_scenario_boundaries(obligations, scenario)

    # Declaring the neighbour records that the edit cannot isolate one duty.
    scenario.declared_affected_ids = ["c.neighbour"]
    validate_scenario_boundaries(obligations, scenario)


def test_the_split_dpa_duties_must_declare_each_other():
    """They share a span, so no scenario can touch one without the other.

    This is the unresolved adjudication showing up in the campaign, and the generator
    records it rather than the validator being told to ignore it.
    """
    campaign = _campaign()
    removed = next(
        s for s in campaign.scenarios
        if s.scenario_id == "dpa.breach_notification.removed"
    )

    assert "dpa.dpia_assistance" in removed.declared_affected_ids


def test_controls_and_injections_must_not_expect_an_answer_change():
    with pytest.raises(ValueError, match="must not expect an answer change"):
        _scenario(kind="semantic_control", expects_answer_change=True,
                  target_obligation_ids=[])

    with pytest.raises(ValueError, match="must expect an answer change"):
        _scenario(kind="obligation_removed", expects_answer_change=False)


def test_an_answer_changing_scenario_needs_a_target():
    with pytest.raises(ValueError, match="needs a target"):
        _scenario(target_obligation_ids=[])


def test_the_campaign_is_marked_candidate_until_gold_is_adjudicated():
    assert _campaign().status == "candidate"
