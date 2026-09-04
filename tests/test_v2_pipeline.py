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


def test_the_v2_review_is_upgraded_from_the_v1_fixture_not_a_second_file():
    """One fixture per case cannot drift from itself.

    The v2 stubs used to be generated and committed alongside the v1 ones, so the two
    could disagree with nothing to catch it.
    """
    from contract_eval.models import ReviewOutput
    from contract_eval.upgrade import upgrade_review

    assert not list(Path("fixtures").glob("*_stub.v2.json")), (
        "v2 fixtures are upgraded on load; a committed copy could drift"
    )

    for case in ALL_CASES:
        v1 = ReviewOutput.model_validate(
            json.loads(Path(f"fixtures/{case}_stub.json").read_text())
        )
        upgraded = upgrade_review(v1)
        from_adapter = get_adapter(False).review_v2(
            source_text=Path(f"data/{case}_sample.md").read_text(), case=case
        )

        assert upgraded == from_adapter
        assert len(upgraded.clauses) == len(v1.clauses)
        assert [f.severity for f in upgraded.risk_flags] == [
            f.severity for f in v1.risk_flags
        ], "severities must not drift in the upgrade"


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


def test_a_v1_gold_set_can_enter_the_v2_path():
    """v1 is an input format now, not a parallel world.

    Before this, conversion lived in a script and only fixtures could cross between
    the two representations. A real v1 gold set could not be scored by the evidence
    path at all.
    """
    from contract_eval.models import ExpectedAnswer
    from contract_eval.upgrade import upgrade_gold

    for case in ALL_CASES:
        source = Path(f"data/{case}_sample.md").read_text()
        v1 = ExpectedAnswer.model_validate(
            json.loads(Path(f"expected/{case}.json").read_text())
        )
        upgraded = upgrade_gold(case, v1, source)

        assert len(upgraded.obligations) == len(v1.clause_types)
        upgraded.validate_against_source(source)
        # A v1 severity has no recorded provenance, so it must not claim to rest on law.
        for obligation in upgraded.obligations:
            if obligation.risk:
                assert obligation.risk.source_category == "legal_judgment"


def test_an_unlocatable_v1_clause_fails_the_upgrade_loudly():
    from contract_eval.models import ExpectedAnswer
    from contract_eval.upgrade import UpgradeError, upgrade_gold

    v1 = ExpectedAnswer.model_validate({
        "clause_types": ["term"],
        "risk_flags": {},
        "clause_anchors": {"term": "a phrase that appears nowhere in the contract"},
    })
    with pytest.raises(UpgradeError, match="matches 0 places"):
        upgrade_gold("nda", v1, Path("data/nda_sample.md").read_text())
