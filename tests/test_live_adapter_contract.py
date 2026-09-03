"""The live adapter's contract, testable without a provider call.

The offline suite runs entirely through the stub, so the live path had no coverage at
all. That is how removing the JSON shape from the prompt also removed the snake_case
convention: a structured-output model returned readable labels like
"Definition of Confidential Information", every clause scored as missed, and clause F1
fell to 0.00 while the review itself was accurate.
"""

import json

from contract_eval.models import Abstention, Citation, Clause, ReviewOutput, RiskFlag


def _schema() -> dict:
    return ReviewOutput.model_json_schema()


def _description(defs: dict, model: str, field: str) -> str:
    return defs[model]["properties"][field].get("description", "")


def test_schema_carries_the_snake_case_convention():
    """With structured outputs the schema is the only place a convention can live.

    The prompt no longer describes the response shape, so a convention stated only in
    prose reaches the model nowhere.
    """
    defs = _schema()["$defs"]

    for model in ("Clause", "RiskFlag", "Citation", "Abstention"):
        description = _description(defs, model, "clause_type")
        assert "snake_case" in description, f"{model}.clause_type must state the convention"


def test_schema_requires_verbatim_quotation():
    """Citation grounding is an exact span match, so the schema must ask for one."""
    description = _description(_schema()["$defs"], "Citation", "quote")

    assert "verbatim" in description.lower()
    assert "paraphrase" in description.lower()


def test_review_output_parses_a_bare_structured_response():
    """Structured output returns the object directly, with no prose to slice out."""
    payload = {
        "clauses": [{"clause_type": "governing_law", "text": "Governed by German law."}],
        "risk_flags": [
            {"clause_type": "term", "severity": "high", "rationale": "perpetual"}
        ],
        "citations": [{"quote": "laws of the Federal Republic", "clause_type": "governing_law"}],
        "abstentions": [],
    }
    parsed = ReviewOutput.model_validate_json(json.dumps(payload))

    assert parsed.clauses[0].clause_type == "governing_law"
    assert parsed.risk_flags[0].severity == "high"


def test_live_adapter_records_effort_and_both_model_identifiers():
    """A score difference between two runs of one commit must be explainable."""
    import inspect

    from contract_eval.adapters import live

    source = inspect.getsource(live)

    # Effort is pinned rather than inherited, and travels with the request.
    assert "CONTRACT_EVAL_EFFORT" in source
    assert "effort=_EFFORT" in source
    # Requested and returned identifiers are recorded separately.
    assert "returned_model=" in source
    # One logical attempt is one provider request.
    assert "max_retries=0" in source


def test_live_adapter_no_longer_slices_json_out_of_prose():
    from contract_eval.adapters import live

    assert not hasattr(live, "_extract_json"), (
        "brace-slicing is the pre-structured-output workaround; the schema now defines "
        "the response shape"
    )
