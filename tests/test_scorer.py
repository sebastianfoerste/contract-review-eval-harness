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
