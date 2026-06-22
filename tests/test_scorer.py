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
