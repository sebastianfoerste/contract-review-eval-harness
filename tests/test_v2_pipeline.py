"""The v2 stack must be reachable from a contract, not merely implemented.

Every piece of it was tested in isolation and none of it was connected: no adapter
produced an evidence-linked review, and no command consumed one. These tests assert
the wiring, which is the property unit tests of the parts cannot show.
"""

import json
from pathlib import Path

import pytest

from contract_eval.adapters import get_adapter
from contract_eval.cases import ALL_CASES
from contract_eval.obligation_cli import evaluate_obligations, load_gold_v2, render
from contract_eval.review_v2 import ReviewOutputV2


def test_every_adapter_can_produce_an_evidence_linked_review():
    """Without this the v2 scorer can never see real output."""
    for case in ALL_CASES:
        source = Path(f"data/{case}_sample.md").read_text()
        review = get_adapter(False).review_v2(source_text=source, case=case)

        assert isinstance(review, ReviewOutputV2)
        assert review.citations, f"{case}: no citations"
        assert any(f.evidence for f in review.clauses), f"{case}: no finding cites anything"


def test_the_live_adapter_requests_the_evidence_schema():
    """A v2 scorer fed by a v1 request would score reviews that cannot bind."""
    import inspect

    from contract_eval.adapters import live

    source = inspect.getsource(live)
    assert "output_format=ReviewOutputV2" in source
    assert "def review_v2" in source


def test_the_pipeline_runs_end_to_end_for_every_case():
    for case in ALL_CASES:
        result = evaluate_obligations(case)

        assert result["case"] == case
        assert result["obligations"]["total"] > 0
        assert 0.0 <= result["obligations"]["covered"] <= 1.0
        assert isinstance(result["evidence"]["unbound_clauses"], list)


def test_the_pipeline_reports_no_decision_while_the_gold_is_a_candidate():
    """The refusal has to reach the output, not just the exception."""
    result = evaluate_obligations("dpa")

    assert result["certificate"] is None
    assert "blind second annotation" in result["certificate_unavailable"]
    assert result["gold_status"]["annotation_status"] == "candidate"

    markdown = render(result)
    assert "Unavailable." in markdown
    assert "single-annotator candidate" in markdown


def test_v2_stubs_preserve_the_v1_fixtures_designed_imperfections():
    """Converted mechanically, so the two paths stay comparable."""
    for case in ALL_CASES:
        v1 = json.loads(Path(f"fixtures/{case}_stub.json").read_text())
        v2 = json.loads(Path(f"fixtures/{case}_stub.v2.json").read_text())

        assert len(v2["clauses"]) == len(v1["clauses"])
        assert len(v2["citations"]) == len(v1["citations"])
        assert len(v2["risk_flags"]) == len(v1["risk_flags"])

        v1_severities = [f["severity"] for f in v1["risk_flags"]]
        v2_severities = [f["severity"] for f in v2["risk_flags"]]
        assert v1_severities == v2_severities, "severities must not drift in conversion"


def test_findings_without_citations_become_visibly_unbound():
    """v1 hid an assertion with nothing behind it; v2 must not."""
    result = evaluate_obligations("nda")

    assert result["evidence"]["unbound_clauses"], (
        "the nda fixture has findings with no citation; they must surface as unbound"
    )


def test_gold_offsets_are_validated_when_the_pipeline_loads_them():
    for case in ALL_CASES:
        gold = load_gold_v2(case)
        source = Path(f"data/{case}_sample.md").read_text()
        for obligation in gold.obligations:
            assert source[obligation.start : obligation.end] == obligation.quote
