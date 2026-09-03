"""Comparing two blind annotations. Statistics are descriptive, never a pass mark."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contract_eval.adjudication import compare, render_ledger
from contract_eval.gold_v2 import ExpectedAnswerV2


def _annotation(case="dpa", annotator="annotator-a", obligations=None):
    raw = deepcopy(json.loads(Path(f"annotations/drafts/{case}.candidate.v2.json").read_text()))
    raw["review_context"]["annotator_id"] = annotator
    if obligations is not None:
        raw["obligations"] = obligations
    return ExpectedAnswerV2.model_validate(raw)


def _ob(oid, start, end, quote, severity=None, category="law", reference="Art. 28(3)"):
    entry = {
        "obligation_id": oid, "label": oid, "description": "d",
        "start": start, "end": end, "quote": quote,
    }
    if severity:
        entry["risk"] = {
            "severity": severity, "rationale": "because",
            "source_category": category, "source_reference": reference,
        }
    return entry


def test_identical_annotations_agree_completely():
    gold = _annotation()
    report = compare(gold, _annotation(annotator="annotator-b"))

    assert report.obligation_agreement == 1.0
    assert report.unresolved() == 0
    assert report.only_in_a == [] and report.only_in_b == []


def test_obligations_match_by_span_not_by_identifier():
    """Two blind annotators will not choose the same names."""
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")
    end = start + 40
    quote = source[start:end]

    a = _annotation(obligations=[_ob("dpa.audit_rights", start, end, quote)])
    b = _annotation(annotator="annotator-b",
                    obligations=[_ob("dpa.inspection_rights", start, end, quote)])

    report = compare(a, b)

    assert report.matched_pairs == [("dpa.audit_rights", "dpa.inspection_rights")]
    assert report.unresolved() == 0


def test_severity_disagreement_is_recorded_not_averaged():
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")
    end = start + 40
    quote = source[start:end]

    a = _annotation(obligations=[_ob("dpa.audit", start, end, quote, severity="high")])
    b = _annotation(annotator="annotator-b",
                    obligations=[_ob("dpa.audit", start, end, quote, severity="medium")])

    report = compare(a, b)

    assert report.severity_agreement == 0.0
    kinds = {d.kind for d in report.disagreements}
    assert "severity" in kinds
    assert report.unresolved() == 1


def test_an_obligation_only_one_annotator_saw_is_a_disagreement():
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")
    quote = source[start:start + 40]

    a = _annotation(obligations=[_ob("dpa.audit", start, start + 40, quote)])
    b = _annotation(annotator="annotator-b", obligations=[
        _ob("dpa.audit", start, start + 40, quote),
        _ob("dpa.extra", 0, 20, source[0:20]),
    ])

    report = compare(a, b)

    assert report.only_in_b == ["dpa.extra"]
    assert any(d.kind == "only_in_b" for d in report.disagreements)


def test_boundary_disagreement_is_recorded_when_spans_only_partly_overlap():
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")

    a = _annotation(obligations=[_ob("dpa.audit", start, start + 60, source[start:start + 60])])
    b = _annotation(annotator="annotator-b",
                    obligations=[_ob("dpa.audit", start, start + 45, source[start:start + 45])])

    report = compare(a, b)

    assert any(d.kind == "boundary" for d in report.disagreements)


def test_source_category_disagreement_is_recorded_separately():
    """A statutory conclusion and a market-practice view are not the same claim."""
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")
    quote = source[start:start + 40]

    a = _annotation(obligations=[
        _ob("dpa.audit", start, start + 40, quote, severity="high", category="law")])
    b = _annotation(annotator="annotator-b", obligations=[
        _ob("dpa.audit", start, start + 40, quote, severity="high",
            category="market_practice", reference=None)])

    report = compare(a, b)

    assert any(d.kind == "source_category" for d in report.disagreements)


def test_kappa_is_undefined_rather_than_flattering_on_a_degenerate_sample():
    """One label used throughout makes expected agreement degenerate."""
    source = Path("data/dpa_sample.md").read_text()
    spans = [(source.index("On-site inspections"), 40),
             (source.index("engage sub-processors"), 30)]

    obligations = [
        _ob(f"dpa.o{i}", s, s + n, source[s:s + n], severity="high")
        for i, (s, n) in enumerate(spans)
    ]
    a = _annotation(obligations=obligations)
    b = _annotation(annotator="annotator-b", obligations=deepcopy(obligations))

    report = compare(a, b)

    assert report.severity_agreement == 1.0
    assert report.weighted_kappa is None, "all-one-label kappa must not be reported"


def test_ledger_names_every_disagreement_and_the_statistics_are_labelled_descriptive():
    source = Path("data/dpa_sample.md").read_text()
    start = source.index("On-site inspections")
    quote = source[start:start + 40]

    a = _annotation(obligations=[_ob("dpa.audit", start, start + 40, quote, severity="high")])
    b = _annotation(annotator="annotator-b",
                    obligations=[_ob("dpa.audit", start, start + 40, quote, severity="low")])

    ledger = render_ledger("dpa", compare(a, b))

    assert "Descriptive statistics" in ledger
    assert "not a pass mark" in ledger
    assert "Unresolved disagreements: 1" in ledger
    assert "written adjudication before the gold set can be frozen" in ledger


def test_comparing_different_cases_is_rejected():
    with pytest.raises(ValueError, match="different cases"):
        compare(_annotation("dpa"), _annotation("nda", annotator="annotator-b"))
