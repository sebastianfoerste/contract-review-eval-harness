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
            # Required: a flagged risk must carry its written justification.
            "severity_rationale": {"term": "high because the term is perpetual"},
        }
    )
    assert exp.risk_flags["term"] == "high"


def test_gold_sets_validate_and_reject_unknown_fields():
    """Structural validation only. It cannot establish that an alias is a synonym."""
    import json
    from pathlib import Path

    import pytest
    from pydantic import ValidationError

    from contract_eval.cases import ALL_CASES
    from contract_eval.models import ExpectedAnswer

    for case in ALL_CASES:
        raw = json.loads(Path(f"expected/{case}.json").read_text())
        expected = ExpectedAnswer.model_validate(raw)
        assert set(expected.severity_rationale) == set(expected.risk_flags)

        with pytest.raises(ValidationError):
            ExpectedAnswer.model_validate({**raw, "_severity_rationale": {"x": "y"}})


def test_alias_validation_is_structural_only():
    """An alias target must exist and must not shadow a canonical name.

    This does NOT prove semantic equivalence: an alias mapping `termination` onto
    `audit_rights` passes every check here. Only human review establishes that an
    alias names the same clause, which is why the annotation guideline requires it.
    """
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    base = {"clause_types": ["audit_rights"], "risk_flags": {}}

    with pytest.raises(ValidationError):
        ExpectedAnswer.model_validate({**base, "clause_aliases": {"x": "not_a_clause"}})
    with pytest.raises(ValidationError):
        ExpectedAnswer.model_validate({**base, "clause_aliases": {"audit_rights": "audit_rights"}})

    # Semantically wrong, structurally valid. Documented, not asserted away.
    ExpectedAnswer.model_validate({**base, "clause_aliases": {"termination": "audit_rights"}})


def test_risk_flags_must_reference_declared_clauses_and_valid_severities():
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    with pytest.raises(ValidationError):
        ExpectedAnswer.model_validate(
            {"clause_types": ["a"], "risk_flags": {"b": "high"}}
        )
    with pytest.raises(ValidationError):
        ExpectedAnswer.model_validate(
            {"clause_types": ["a"], "risk_flags": {"a": "catastrophic"}}
        )


def test_severity_rationale_must_match_risk_flags_exactly():
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    with pytest.raises(ValidationError):
        ExpectedAnswer.model_validate({
            "clause_types": ["a", "b"],
            "risk_flags": {"a": "high", "b": "low"},
            "severity_rationale": {"a": "because"},
        })


def test_every_gold_set_states_whose_review_it_encodes():
    """A severity without a stated party is not defensible."""
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.models import ExpectedAnswer

    for case in ALL_CASES:
        expected = ExpectedAnswer.model_validate(
            json.loads(Path(f"expected/{case}.json").read_text())
        )
        context = expected.review_context
        assert context is not None, f"{case}: no review_context"
        assert context.party and context.governing_law and context.objective


def test_every_clause_type_has_an_anchor():
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.models import ExpectedAnswer

    for case in ALL_CASES:
        expected = ExpectedAnswer.model_validate(
            json.loads(Path(f"expected/{case}.json").read_text())
        )
        assert set(expected.clause_anchors) == set(expected.clause_types)


def _minimal(**overrides):
    base = {
        "clause_types": ["audit_rights", "term"],
        "risk_flags": {"audit_rights": "high"},
        "severity_rationale": {"audit_rights": "high because the inspection right is excluded"},
    }
    base.update(overrides)
    return base


def test_risk_flag_without_any_rationale_map_fails():
    """The bypass this rule exists to prevent: a flag with no justification at all."""
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    payload = _minimal()
    del payload["severity_rationale"]
    with pytest.raises(ValidationError, match="exactly one entry per risk flag"):
        ExpectedAnswer.model_validate(payload)


def test_risk_flag_with_empty_rationale_map_fails():
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    with pytest.raises(ValidationError, match="exactly one entry per risk flag"):
        ExpectedAnswer.model_validate(_minimal(severity_rationale={}))


def test_blank_rationale_fails():
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    with pytest.raises(ValidationError, match="must not be blank"):
        ExpectedAnswer.model_validate(_minimal(severity_rationale={"audit_rights": "   \n"}))


def test_missing_and_extra_rationales_fail():
    import pytest
    from pydantic import ValidationError

    from contract_eval.models import ExpectedAnswer

    with pytest.raises(ValidationError, match="missing="):
        ExpectedAnswer.model_validate(
            _minimal(risk_flags={"audit_rights": "high", "term": "low"})
        )
    with pytest.raises(ValidationError, match="unexpected="):
        ExpectedAnswer.model_validate(
            _minimal(severity_rationale={"audit_rights": "x", "term": "y"})
        )


def test_committed_gold_sets_still_validate():
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.models import ExpectedAnswer

    for case in ALL_CASES:
        ExpectedAnswer.model_validate(json.loads(Path(f"expected/{case}.json").read_text()))
