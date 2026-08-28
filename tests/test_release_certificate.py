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

    assert certificate["schema"] == "contract-review-eval.release-certificate.v1"
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
        case_scores.update(
            {
                "clause_precision": 1.0,
                "clause_recall": 1.0,
                "clause_f1": 1.0,
                "risk_flag_accuracy": 1.0,
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
