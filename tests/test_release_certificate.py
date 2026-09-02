from copy import deepcopy
from pathlib import Path

from contract_eval.cases import ALL_CASES
from contract_eval.cli import evaluate_case
from contract_eval.release_certificate import (
    build_release_certificate,
    render_release_certificate,
    verify_release_certificate,
)


def _scores():
    return {
        case: evaluate_case(case, live=False)
        for case in ALL_CASES
    }


def test_release_certificate_rejects_seeded_unsupported_citations():
    certificate = build_release_certificate(_scores())

    assert certificate["schema"] == "contract-review-eval.release-certificate.v3"
    assert certificate["suite_decision"] == "REJECT"
    # Every case fixture seeds exactly one fabricated citation, so each is rejected.
    assert certificate["summary"]["rejected"] == len(ALL_CASES)
    assert certificate["summary"]["total_unsupported_citations"] == len(ALL_CASES)
    assert all(
        "unsupported_citation_detected" in result["blockers"]
        for result in certificate["cases"]
    )
    assert certificate["external_actions_allowed"] is False
    assert len(certificate["integrity_sha256"]) == 64


def test_release_certificate_is_input_bound_and_deterministic():
    first = build_release_certificate(_scores(), root=Path("."))
    second = build_release_certificate(_scores(), root=Path("."))

    assert first == second
    assert all(
        len(result["input_manifest_sha256"]) == 64
        for result in first["cases"]
    )


def test_perfect_scores_are_only_pilot_eligible():
    scores = deepcopy(_scores())
    for case_scores in scores.values():
        # Under policy v2 "perfect" means the risk metrics too, not just the legacy
        # accuracy figure that could not see over-flagging.
        case_scores.update(
            {
                "clause_precision": 1.0,
                "clause_recall": 1.0,
                "clause_f1": 1.0,
                "risk_flag_accuracy": 1.0,
                "risk_precision": 1.0,
                "risk_recall": 1.0,
                "risk_f1": 1.0,
                "risk_severity_accuracy": 1.0,
                "risk_false_positives": [],
                "risk_missed": [],
                "risk_duplicate_flags": [],
                "risk_conflicting_flags": [],
                "citation_grounding": 1.0,
                "hallucination_count": 0,
            }
        )

    certificate = build_release_certificate(scores)

    assert certificate["suite_decision"] == "PILOT_ELIGIBLE"
    assert "never authorizes deployment" in certificate["review_gate"]


def test_markdown_surfaces_policy_and_failure_register():
    markdown = render_release_certificate(build_release_certificate(_scores()))

    assert "Contract Review Release Certificate" in markdown
    assert "Suite decision: REJECT" in markdown
    assert "Failure register" in markdown


def test_release_certificate_verifier_reproduces_the_suite():
    scores = _scores()
    certificate = build_release_certificate(scores)

    verification = verify_release_certificate(certificate, scores)

    assert verification["status"] == "VALID"
    assert verification["errors"] == []
    assert verification["verified_cases"] == sorted(ALL_CASES)
    assert len(verification["verification_sha256"]) == 64


def test_release_certificate_verifier_detects_tampering_and_score_drift():
    scores = _scores()
    certificate = build_release_certificate(scores)
    tampered = deepcopy(certificate)
    target = next(
        result for result in tampered["cases"] if result["case"] == "nda"
    )
    target["scores"]["clause_recall"] = 0.0

    verification = verify_release_certificate(tampered, scores)

    assert verification["status"] == "INVALID"
    assert "certificate_integrity_mismatch" in verification["errors"]
    assert "nda:score_reproduction_mismatch" in verification["errors"]


def _clean_scores():
    """A case that would qualify for pilot eligibility under policy v2."""
    return {
        "clause_precision": 1.0,
        "clause_recall": 1.0,
        "clause_f1": 1.0,
        "risk_flag_accuracy": 1.0,
        "risk_precision": 1.0,
        "risk_recall": 1.0,
        "risk_f1": 1.0,
        "risk_severity_accuracy": 1.0,
        "risk_false_positives": [],
        "risk_missed": [],
        "risk_severity_confusion": {},
        "risk_duplicate_flags": [],
        "risk_conflicting_flags": [],
        "span_coverage": 1.0,
        "citation_grounded": 5,
        "citation_total": 5,
        "citation_grounding": 1.0,
        "hallucination_count": 0,
        "thresholds": {},
    }


def test_twenty_spurious_high_risk_flags_prevent_pilot_eligibility():
    """The headline acceptance criterion: over-flagging must cost eligibility."""
    from contract_eval.release_certificate import build_release_certificate

    clean = build_release_certificate({"nda": _clean_scores()})
    assert clean["cases"][0]["decision"] == "PILOT_ELIGIBLE"

    noisy = _clean_scores()
    noisy["risk_false_positives"] = [f"spurious_{i}" for i in range(20)]
    noisy["risk_precision"] = 0.05
    noisy["risk_f1"] = 0.1

    result = build_release_certificate({"nda": noisy})["cases"][0]
    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert "risk_false_positive" in result["review_items"]


def test_conflicting_flags_prevent_pilot_eligibility():
    from contract_eval.release_certificate import build_release_certificate

    scores = _clean_scores()
    scores["risk_duplicate_flags"] = ["subprocessors"]
    scores["risk_conflicting_flags"] = ["subprocessors"]

    result = build_release_certificate({"nda": scores})["cases"][0]
    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert "conflicting_risk_flags" in result["review_items"]


def test_unsupported_citation_is_a_hard_blocker():
    from contract_eval.release_certificate import build_release_certificate

    scores = _clean_scores()
    scores["hallucination_count"] = 1

    result = build_release_certificate({"nda": scores})["cases"][0]
    assert result["decision"] == "REJECT"


def test_unknown_certificate_schema_fails_with_an_actionable_error():
    from contract_eval.release_certificate import verify_release_certificate

    verification = verify_release_certificate(
        {"schema": "contract-review-eval.release-certificate.v9", "integrity_sha256": "x"}, {}
    )
    assert verification["status"] == "INVALID"
    assert "certificate_schema_unsupported" in verification["errors"][0]
    assert "v9" in verification["errors"][0]


def test_legacy_v1_certificates_remain_verifiable():
    """A v1 decision was issued under the legacy policy and is not re-decided."""
    from contract_eval.release_certificate import (
        V1_SCHEMA,
        _canonical_sha256,
        verify_release_certificate,
    )

    payload = {"schema": V1_SCHEMA, "suite_decision": "REJECT", "cases": []}
    certificate = {**payload, "integrity_sha256": _canonical_sha256(payload)}

    verification = verify_release_certificate(certificate, {})
    assert verification["status"] == "VALID"
    assert verification["verification_scope"] == "integrity_only"


def _eligible_scores():
    """A case satisfying every requirement in the registry."""
    from contract_eval.release_certificate import DIAGNOSTIC_METRICS, REQUIREMENTS

    scores = {}
    for requirement in REQUIREMENTS:
        if requirement.comparator == "gte":
            scores[requirement.metric] = requirement.threshold
        elif requirement.comparator == "zero":
            scores[requirement.metric] = 0
        elif requirement.comparator == "empty":
            scores[requirement.metric] = []
    for metric in DIAGNOSTIC_METRICS:
        scores.setdefault(metric, 0)
    scores["risk_severity_confusion"] = {}
    scores["span_uncovered_clauses"] = []
    return scores


def _violate(scores, requirement):
    scores = dict(scores)
    if requirement.comparator == "gte":
        scores[requirement.metric] = 0.5
    elif requirement.comparator == "zero":
        scores[requirement.metric] = 1
    elif requirement.comparator == "empty":
        scores[requirement.metric] = ["something"]
    return scores


def test_every_requirement_fails_in_isolation_with_its_declared_code_and_class():
    """Each registry entry must be individually load-bearing."""
    from contract_eval.release_certificate import REQUIREMENTS, build_release_certificate

    baseline = build_release_certificate({"nda": _eligible_scores()})["cases"][0]
    assert baseline["decision"] == "PILOT_ELIGIBLE"

    for requirement in REQUIREMENTS:
        result = build_release_certificate(
            {"nda": _violate(_eligible_scores(), requirement)}
        )["cases"][0]

        if requirement.failure_class == "blocker":
            assert result["decision"] == "REJECT", requirement.requirement_id
            assert requirement.failure_code in result["blockers"], requirement.requirement_id
        else:
            assert result["decision"] == "HUMAN_REVIEW_REQUIRED", requirement.requirement_id
            assert requirement.failure_code in result["review_items"], requirement.requirement_id


def test_every_decision_input_is_published_in_every_case():
    from contract_eval.release_certificate import REQUIREMENTS, build_release_certificate

    certificate = build_release_certificate({"nda": _eligible_scores()})
    for result in certificate["cases"]:
        for requirement in REQUIREMENTS:
            assert requirement.metric in result["scores"], requirement.metric


def test_legacy_risk_accuracy_cannot_affect_the_decision():
    """It is a diagnostic. Driving it to zero must not change eligibility."""
    from contract_eval.release_certificate import build_release_certificate

    scores = _eligible_scores()
    scores["risk_flag_accuracy"] = 0.0

    result = build_release_certificate({"nda": scores})["cases"][0]
    assert result["decision"] == "PILOT_ELIGIBLE"
    assert "risk_flag_accuracy" not in result["scores"]
    assert result["diagnostics"]["risk_flag_accuracy"] == 0.0


def test_missing_decision_input_fails_loudly():
    """A certificate must never be issued while a decision input is absent."""
    import pytest

    from contract_eval.release_certificate import build_release_certificate

    scores = _eligible_scores()
    del scores["risk_precision"]

    with pytest.raises(KeyError, match="risk_precision"):
        build_release_certificate({"nda": scores})


def test_twenty_spurious_flags_still_prevent_eligibility_under_v3():
    from contract_eval.release_certificate import build_release_certificate

    scores = _eligible_scores()
    scores["risk_precision"] = 0.05
    scores["risk_false_positives"] = [f"spurious_{i}" for i in range(20)]

    result = build_release_certificate({"nda": scores})["cases"][0]
    assert result["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert "risk_false_positive" in result["review_items"]


def test_frozen_v2_certificate_verifies_at_full_v2_scope():
    """A historical v2 artifact stays reproducible by its own frozen builder."""
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.cli import evaluate_case
    from contract_eval.release_certificate import verify_release_certificate

    certificate = json.loads(
        Path("tests/fixtures/frozen-release-certificate-v2.json").read_text()
    )
    scores = {case: evaluate_case(case, live=False) for case in ALL_CASES}

    verification = verify_release_certificate(certificate, scores)
    assert verification["status"] == "VALID"
    assert verification["verification_scope"] == "full_v2"


def test_v2_certificate_with_drifted_inputs_degrades_to_integrity_only(tmp_path):
    """Once an input moves, the historical decision cannot be recomputed against it."""
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.cli import evaluate_case
    from contract_eval.release_certificate import verify_release_certificate

    certificate = json.loads(
        Path("tests/fixtures/frozen-release-certificate-v2.json").read_text()
    )
    # Point one recorded input at a path whose bytes differ from the record.
    certificate["cases"][0]["input_manifest"]["source_contract"]["sha256"] = "0" * 64

    scores = {case: evaluate_case(case, live=False) for case in ALL_CASES}
    verification = verify_release_certificate(certificate, scores)

    assert verification["verification_scope"] == "integrity_only"
    assert any("changed" in entry for entry in verification["input_drift"])
    assert "re-issue" in verification["note"]


def test_current_v3_certificate_reproduces_and_verifies():
    import json
    from pathlib import Path

    from contract_eval.cases import ALL_CASES
    from contract_eval.cli import evaluate_case
    from contract_eval.release_certificate import (
        build_release_certificate,
        verify_release_certificate,
    )

    committed = json.loads(Path("examples/release-certificate.json").read_text())
    scores = {case: evaluate_case(case, live=False) for case in ALL_CASES}

    assert build_release_certificate(scores) == committed, "committed artifact must reproduce"

    verification = verify_release_certificate(committed, scores)
    assert verification["status"] == "VALID"
    assert verification["verification_scope"] == "full"
