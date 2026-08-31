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


def test_clause_aliases_are_synonyms_not_shortcuts():
    """An alias renames a clause; it must never point at a different one.

    Without this, an alias map could quietly accept a wrong answer — which is the
    failure mode the harness exists to catch, reintroduced in the gold set itself.
    """
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.models import ExpectedAnswer

    for case in ALL_CASES:
        expected = ExpectedAnswer.model_validate(
            json.loads(Path(f"expected/{case}.json").read_text())
        )
        canonical = set(expected.clause_types)
        for alias, target in expected.clause_aliases.items():
            assert target in canonical, f"{case}: alias {alias!r} targets unknown {target!r}"
            assert alias not in canonical, f"{case}: alias {alias!r} shadows a canonical name"
