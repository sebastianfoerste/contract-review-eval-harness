from contract_eval.models import ReviewOutput, ExpectedAnswer


def test_review_output_roundtrips():
    out = ReviewOutput.model_validate(
        {
            "clauses": [{"clause_type": "confidentiality", "text": "..."}],
            "risk_flags": [{"clause_type": "term", "severity": "high", "rationale": "perpetual"}],
            "citations": [{"quote": "shall remain confidential", "clause_type": "confidentiality"}],
        }
    )
    assert out.clauses[0].clause_type == "confidentiality"
    assert out.risk_flags[0].severity == "high"


def test_expected_answer_parses_severity_map():
    exp = ExpectedAnswer.model_validate(
        {
            "clause_types": ["confidentiality", "term"],
            "risk_flags": {"term": "high"},
        }
    )
    assert exp.risk_flags["term"] == "high"
