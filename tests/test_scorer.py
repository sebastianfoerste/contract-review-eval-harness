from contract_eval.models import Citation
from contract_eval.scorer import (
    citation_grounding,
    clause_scores,
    count_hallucinations,
    risk_flag_accuracy,
)


def test_clause_scores_f1():
    s = clause_scores(expected=["a", "b", "c", "d"], predicted=["a", "b", "x"])
    assert round(s.precision, 3) == 0.667  # 2 of 3 predicted correct
    assert s.recall == 0.5  # 2 of 4 expected found
    assert round(s.f1, 3) == 0.571


def test_risk_flag_accuracy_partial():
    acc = risk_flag_accuracy(
        expected={"term": "high", "definition": "medium"},
        predicted={"term": "high", "definition": "low"},
    )
    assert acc == 0.5  # 1 of 2 severities matched


def test_citation_grounding_and_hallucinations():
    source = "The Receiving Party shall keep all Confidential Information secret."
    citations = [
        Citation(quote="keep all Confidential Information secret", clause_type="confidentiality"),
        Citation(quote="auto-renews every 99 years", clause_type="term"),  # fabricated
    ]
    cs = citation_grounding(source, citations)
    assert cs.grounded == 1
    assert cs.total == 2
    assert cs.grounding_rate == 0.5
    assert count_hallucinations(source, citations) == 1


def test_risk_metrics_penalise_false_positives():
    """risk_flag_accuracy alone cannot see over-flagging; risk precision must."""
    from contract_eval.scorer import risk_flag_accuracy, risk_metrics

    expected = {"term": "high"}
    predicted = {"term": "high", **{f"spurious_{i}": "high" for i in range(20)}}

    assert risk_flag_accuracy(expected, predicted) == 1.0

    risk = risk_metrics(expected, predicted)
    assert risk.recall == 1.0
    assert risk.precision < 0.05
    assert len(risk.false_positives) == 20
    assert risk.severity_accuracy == 1.0


def test_risk_metrics_separate_missed_risk_from_wrong_severity():
    from contract_eval.scorer import risk_metrics

    expected = {"a": "high", "b": "high"}
    risk = risk_metrics(expected, {"a": "low"})

    assert risk.missed == ["b"]
    assert risk.identified == 1
    assert risk.severity_accuracy == 0.0
    assert risk.severity_confusion == {"high->low": 1}


def test_grounding_requires_a_contiguous_span_not_token_overlap():
    """A reordered quote is not a quotation.

    The previous implementation compared unordered token sets at 85% overlap, so
    shuffled words scored as grounded.
    """
    from contract_eval.models import Citation
    from contract_eval.scorer import citation_grounding, grounded_span

    source = "The Receiving Party shall keep all Confidential Information secret."

    assert grounded_span(source, "shall keep all Confidential Information secret") is not None
    assert grounded_span(source, "Confidential secret Information keep all shall") is None
    assert grounded_span(source, "shall keep all Confidential Information public") is None

    score = citation_grounding(source, [Citation(quote="keep all Confidential", clause_type="c")])
    assert score.grounded == 1
    assert score.spans[0] is not None


def _nda():
    import json
    from pathlib import Path

    from contract_eval.models import ExpectedAnswer

    src = Path("data/nda_sample.md").read_text()
    exp = ExpectedAnswer.model_validate(json.loads(Path("expected/nda.json").read_text()))
    return src, exp


def test_span_coverage_is_independent_of_clause_labels():
    """The whole point: renaming a clause must not change coverage."""
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    quote = "shall remain in effect in perpetuity"

    gold_name = span_coverage(src, exp.clause_anchors, [Citation(quote=quote, clause_type="term")])
    odd_name = span_coverage(
        src, exp.clause_anchors, [Citation(quote=quote, clause_type="duration_of_obligations")]
    )
    assert gold_name.coverage == odd_name.coverage
    assert gold_name.covered == odd_name.covered == ["term"]


def test_span_coverage_discriminates():
    """It must be able to fail, and a single quote must not satisfy its neighbours."""
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    total = len(exp.clause_anchors)

    assert span_coverage(src, exp.clause_anchors, []).coverage == 0.0

    one = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote="shall remain in effect in perpetuity", clause_type="term")],
    )
    assert one.coverage == 1 / total
    assert one.covered == ["term"]

    everything = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote=a, clause_type=c) for c, a in exp.clause_anchors.items()],
    )
    assert everything.coverage == 1.0
    assert everything.uncovered == []


def test_ungrounded_citations_do_not_earn_coverage():
    from contract_eval.models import Citation
    from contract_eval.scorer import span_coverage

    src, exp = _nda()
    result = span_coverage(
        src,
        exp.clause_anchors,
        [Citation(quote="a clause that does not appear anywhere", clause_type="term")],
    )
    assert result.coverage == 0.0
    assert result.unlocated_citations == 1


def test_duplicate_canonical_risk_flags_are_visible_not_silently_merged():
    """Two labels collapsing onto one clause used to keep whichever came last."""
    from contract_eval.cli import canonicalise_risk_flags
    from contract_eval.models import RiskFlag

    aliases = {"sub_processors": "subprocessors"}

    conflicting = [
        RiskFlag(clause_type="sub_processors", severity="high", rationale="a"),
        RiskFlag(clause_type="subprocessors", severity="low", rationale="b"),
    ]
    flags, duplicates, conflicts = canonicalise_risk_flags(conflicting, aliases)
    assert duplicates == ["subprocessors"]
    assert conflicts == ["subprocessors"], "contradictory severities must be a conflict"
    assert flags["subprocessors"] == "high", "first prediction wins, deterministically"

    agreeing = [
        RiskFlag(clause_type="sub_processors", severity="high", rationale="a"),
        RiskFlag(clause_type="subprocessors", severity="high", rationale="b"),
    ]
    _, duplicates, conflicts = canonicalise_risk_flags(agreeing, aliases)
    assert duplicates == ["subprocessors"]
    assert conflicts == [], "a repeated flag agreeing with itself is not a conflict"
