from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from contract_eval.adapters import get_adapter
from contract_eval.cli import evaluate_case
from contract_eval.models import ReviewOutput
from contract_eval.release_certificate import build_release_certificate
from contract_eval.robustness import (
    REPORT_SCHEMA,
    apply_mutations,
    build_robustness_report,
    load_campaign,
    render_robustness_html,
    render_robustness_markdown,
    verify_robustness_report,
)

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "robustness" / "campaign.v1.json"


def _report() -> dict:
    scores = {
        case: evaluate_case(case, live=False)
        for case in ("nda", "saas")
    }
    return build_robustness_report(
        CAMPAIGN,
        get_adapter(False),
        build_release_certificate(scores, root=ROOT),
        root=ROOT,
    )


def test_campaign_has_twelve_exact_minimal_pair_scenarios() -> None:
    campaign = load_campaign(CAMPAIGN)
    assert len(campaign.scenarios) == 12
    assert sum(
        scenario.category == "semantic_control"
        for scenario in campaign.scenarios
    ) == 2
    assert {
        scenario.base_case for scenario in campaign.scenarios
    } == {"nda", "saas"}

    for scenario in campaign.scenarios:
        source = (ROOT / "data" / f"{scenario.base_case}_sample.md").read_text()
        mutated = apply_mutations(source, scenario.operations)
        assert mutated != source
        assert apply_mutations(source, scenario.operations) == mutated


def test_mutation_rejects_missing_or_ambiguous_anchor() -> None:
    scenario = load_campaign(CAMPAIGN).scenarios[0]
    with pytest.raises(ValueError, match="exactly once"):
        apply_mutations("anchor anchor", scenario.operations)
    with pytest.raises(ValueError, match="exactly once"):
        apply_mutations("no matching source", scenario.operations)


def test_report_catches_false_reassurance_citations_and_missing_abstention() -> None:
    report = _report()
    metrics = report["metrics"]

    assert report["schema"] == REPORT_SCHEMA
    assert report["suite_decision"] == "REJECT"
    assert report["baseline_release_certificate"]["suite_decision"] == "REJECT"
    assert metrics["scenarios"] == 12
    assert metrics["critical_false_reassurance"] > 0
    assert metrics["unsupported_citations"] > 0
    assert metrics["abstention_compliance"] == 0.0
    assert metrics["semantic_invariance_failures"] == 0
    assert metrics["injection_resilience"] == 1.0
    assert "required_abstention_missing" in report["failure_register"]
    assert report["external_actions_allowed"] is False


def test_report_is_deterministic_and_verifier_detects_tampering() -> None:
    report = _report()
    expected = _report()
    assert report == expected
    assert verify_robustness_report(report, expected)["status"] == "VALID"

    tampered = deepcopy(report)
    tampered["metrics"]["critical_scenario_recall"] = 1.0
    verification = verify_robustness_report(tampered, expected)
    assert verification["status"] == "INVALID"
    assert "report_integrity_mismatch" in verification["errors"]
    assert "report_reproduction_mismatch" in verification["errors"]


def test_renderers_expose_gate_and_review_matrix() -> None:
    report = _report()
    markdown = render_robustness_markdown(report)
    document = render_robustness_html(report)

    assert "Adversarial Contract Robustness Lab" in markdown
    assert "Critical false reassurance" in markdown
    assert "Scenario matrix" in document
    assert report["integrity_sha256"] in document


def test_existing_fixtures_remain_compatible_with_optional_abstentions() -> None:
    payload = json.loads((ROOT / "fixtures" / "nda_stub.json").read_text())
    output = ReviewOutput.model_validate(payload)
    assert output.abstentions == []
