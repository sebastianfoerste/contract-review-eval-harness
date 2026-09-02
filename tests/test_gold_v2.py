"""Gold v2 obligations must be locatable in the raw source, exactly."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from contract_eval.cases import ALL_CASES
from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.scorer import build_normalized_index, normalize_text


def _minimal(**overrides):
    base = {
        "schema": "contract-review-eval.expected-answer.v2",
        "case": "nda",
        "review_context": {
            "party": "Disclosing Party",
            "commercial_perspective": "receiving side",
            "governing_law": "Germany",
            "jurisdiction": "Germany",
            "objective": "pre-signature review",
            "risk_appetite": "conservative",
            "legal_position_date": "2026-09-02",
            "annotator_id": "annotator-a",
            "annotation_status": "candidate",
            "adjudication_status": "not_started",
        },
        "obligations": [{
            "obligation_id": "nda.term",
            "label": "Term",
            "description": "d",
            "start": 0,
            "end": 5,
            "quote": "abcde",
        }],
    }
    base.update(overrides)
    return base


def test_candidate_sets_validate_and_every_offset_matches_the_source():
    """The invariant everything else rests on."""
    total = 0
    for case in ALL_CASES:
        gold = ExpectedAnswerV2.model_validate(
            json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text())
        )
        source = Path(f"data/{case}_sample.md").read_text()
        gold.validate_against_source(source)
        for obligation in gold.obligations:
            assert source[obligation.start : obligation.end] == obligation.quote
        total += len(gold.obligations)
    assert total == 33, "32 v1 concepts with the composite DPA clause split in two"


def test_quote_disagreeing_with_offsets_is_rejected():
    gold = ExpectedAnswerV2.model_validate(_minimal())
    with pytest.raises(ValueError, match="does not match the recorded quote"):
        gold.validate_against_source("zzzzz and more")


def test_offsets_past_the_end_of_the_source_are_rejected():
    gold = ExpectedAnswerV2.model_validate(_minimal())
    with pytest.raises(ValueError, match="exceeds source length"):
        gold.validate_against_source("abc")


def test_offsets_are_python_characters_not_utf8_bytes():
    """A source with non-ASCII text must not shift every later span.

    'Löschung' is three bytes in UTF-8 for the umlaut but one character. Byte offsets
    would silently misplace every obligation after the first umlaut in a German clause.
    """
    source = "Löschung und Rückgabe der Daten."
    start = source.index("Rückgabe")
    end = start + len("Rückgabe")

    gold = ExpectedAnswerV2.model_validate(_minimal(obligations=[{
        "obligation_id": "nda.return",
        "label": "Return",
        "description": "d",
        "start": start,
        "end": end,
        "quote": "Rückgabe",
    }]))
    gold.validate_against_source(source)

    assert len(source.encode("utf-8")) != len(source), "fixture must contain multi-byte characters"


def test_duplicate_and_misprefixed_obligation_ids_are_rejected():
    duplicate = _minimal(obligations=[
        {"obligation_id": "nda.term", "label": "a", "description": "d",
         "start": 0, "end": 3, "quote": "abc"},
        {"obligation_id": "nda.term", "label": "b", "description": "d",
         "start": 4, "end": 7, "quote": "def"},
    ])
    with pytest.raises(ValidationError, match="duplicate obligation ids"):
        ExpectedAnswerV2.model_validate(duplicate)

    with pytest.raises(ValidationError, match="must start with"):
        ExpectedAnswerV2.model_validate(_minimal(obligations=[{
            "obligation_id": "saas.term", "label": "a", "description": "d",
            "start": 0, "end": 3, "quote": "abc",
        }]))


def test_identical_spans_require_an_adjudication_note():
    """One sentence may carry two duties, but not silently."""
    shared = [
        {"obligation_id": "nda.a", "label": "a", "description": "d",
         "start": 0, "end": 3, "quote": "abc"},
        {"obligation_id": "nda.b", "label": "b", "description": "d",
         "start": 0, "end": 3, "quote": "abc"},
    ]
    with pytest.raises(ValidationError, match="adjudication_note"):
        ExpectedAnswerV2.model_validate(_minimal(obligations=shared))

    documented = [{**o, "adjudication_note": "two duties in one sentence"} for o in shared]
    ExpectedAnswerV2.model_validate(_minimal(obligations=documented))


def test_severity_and_rationale_are_inseparable():
    from contract_eval.gold_v2 import ObligationRisk

    with pytest.raises(ValidationError):
        ObligationRisk.model_validate({"severity": "high", "source_category": "law"})
    with pytest.raises(ValidationError, match="non-whitespace"):
        ObligationRisk.model_validate({
            "severity": "high", "rationale": "   ",
            "source_category": "legal_judgment",
        })


def test_statutory_conclusions_must_cite_a_provision():
    """A market-practice view need not cite; a legal conclusion must."""
    from contract_eval.gold_v2 import ObligationRisk

    with pytest.raises(ValidationError, match="requires a source_reference"):
        ObligationRisk.model_validate({
            "severity": "high", "rationale": "mandatory element removed",
            "source_category": "law",
        })

    ObligationRisk.model_validate({
        "severity": "medium", "rationale": "worse than market",
        "source_category": "market_practice",
    })


def test_the_dpa_composite_clause_is_split_into_two_obligations():
    gold = ExpectedAnswerV2.model_validate(
        json.loads(Path("annotations/drafts/dpa.candidate.v2.json").read_text())
    )
    ids = {o.obligation_id for o in gold.obligations}

    assert "dpa.breach_notification" in ids
    assert "dpa.dpia_assistance" in ids
    assert "dpa.breach_and_dpia_assistance" not in ids

    # Their separate calibration is explicitly unresolved, not quietly assumed.
    for obligation in gold.obligations:
        if obligation.obligation_id in ("dpa.breach_notification", "dpa.dpia_assistance"):
            assert obligation.adjudication_note
            assert "NOT yet calibrated" in obligation.risk.rationale


def test_candidate_sets_are_not_authoritative():
    """Nothing here may be mistaken for frozen gold."""
    for case in ALL_CASES:
        gold = ExpectedAnswerV2.model_validate(
            json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text())
        )
        assert gold.review_context.annotation_status == "candidate"
        assert gold.review_context.adjudication_status == "not_started"
        assert "NOT AUTHORITATIVE" in gold.comment


def test_normalized_index_round_trips_and_finds_every_occurrence():
    source = Path("data/nda_sample.md").read_text()
    index = build_normalized_index(source)

    assert index.normalized == normalize_text(source)

    spans = index.find_all(normalize_text("shall remain in effect in perpetuity"))
    assert len(spans) == 1
    start, end = spans[0]
    # The clause wraps a line, so the raw slice is not the normalised phrase.
    assert normalize_text(source[start:end]) == normalize_text(
        "shall remain in effect in perpetuity"
    )
    assert "\n" in source[start:end]
