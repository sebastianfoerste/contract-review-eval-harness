"""Deterministic, input-bound release decisions for a contract-review adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "contract-review-eval.release-certificate.v2"
LEGACY_SCHEMA = "contract-review-eval.release-certificate.v1"
POLICY_ID = "contract-review-eval.strict-legal-release-policy.v2"
LEGACY_POLICY_ID = "contract-review-eval.strict-legal-release-policy.v1"
VERIFICATION_SCHEMA = "contract-review-eval.release-certificate-verification.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _case_decision(case: str, scores: dict[str, Any], root: Path) -> dict[str, Any]:
    blockers: list[str] = []
    review_items: list[str] = []

    # Release policy v2. A citation problem is a hard blocker because an unsupported
    # quotation misrepresents the document. Everything else routes to human review:
    # the gold set is one annotator's judgment, so a metric mismatch is a question
    # for a lawyer rather than an automatic rejection.
    if scores["hallucination_count"] > 0:
        blockers.append("unsupported_citation_detected")
    if scores["citation_grounding"] < 1.0:
        blockers.append("citation_grounding_below_100_percent")

    if scores["clause_recall"] < 1.0:
        review_items.append("expected_clause_missed")
    if scores["clause_precision"] < 1.0:
        review_items.append("unexpected_clause_extracted")
    if scores.get("risk_recall", 1.0) < 1.0:
        review_items.append("expected_risk_missed")
    if scores.get("risk_precision", 1.0) < 1.0:
        review_items.append("risk_false_positive")
    if scores.get("risk_severity_accuracy", 1.0) < 1.0:
        review_items.append("risk_severity_mismatch")
    if scores.get("risk_duplicate_flags"):
        review_items.append("duplicate_risk_flags")
    if scores.get("risk_conflicting_flags"):
        review_items.append("conflicting_risk_flags")

    if blockers:
        decision = "REJECT"
    elif review_items:
        decision = "HUMAN_REVIEW_REQUIRED"
    else:
        decision = "PILOT_ELIGIBLE"

    inputs = {
        "source_contract": {
            "path": f"data/{case}_sample.md",
            "sha256": _sha256(root / "data" / f"{case}_sample.md"),
        },
        "expected_answer": {
            "path": f"expected/{case}.json",
            "sha256": _sha256(root / "expected" / f"{case}.json"),
        },
        "adapter_output": {
            "path": f"fixtures/{case}_stub.json",
            "sha256": _sha256(root / "fixtures" / f"{case}_stub.json"),
        },
    }
    return {
        "case": case,
        "decision": decision,
        "blockers": blockers,
        "review_items": review_items,
        "scores": {
            "clause_precision": scores["clause_precision"],
            "clause_recall": scores["clause_recall"],
            "clause_f1": scores["clause_f1"],
            "risk_flag_accuracy": scores["risk_flag_accuracy"],
            "citation_grounding": scores["citation_grounding"],
            "hallucination_count": scores["hallucination_count"],
        },
        "input_manifest": inputs,
        "input_manifest_sha256": _canonical_sha256(inputs),
    }


def build_release_certificate(
    case_scores: dict[str, dict[str, Any]],
    *,
    root: Path = Path("."),
) -> dict[str, Any]:
    """Build a strict release certificate over one or more synthetic benchmark cases."""

    if not case_scores:
        raise ValueError("release certificate requires at least one evaluated case")
    case_results = [
        _case_decision(case, case_scores[case], root)
        for case in sorted(case_scores)
    ]
    decisions = {result["decision"] for result in case_results}
    if "REJECT" in decisions:
        suite_decision = "REJECT"
    elif "HUMAN_REVIEW_REQUIRED" in decisions:
        suite_decision = "HUMAN_REVIEW_REQUIRED"
    else:
        suite_decision = "PILOT_ELIGIBLE"

    payload = {
        "schema": SCHEMA,
        "policy": {
            "policy_id": POLICY_ID,
            "requirements": {
                "citation_grounding_minimum": 1.0,
                "hallucination_count_maximum": 0,
                "clause_precision_target": 1.0,
                "clause_recall_target": 1.0,
                "risk_flag_accuracy_target": 1.0,
            },
            "hard_blockers": [
                "unsupported citation",
                "citation grounding below 100 percent",
            ],
        },
        "suite_decision": suite_decision,
        "summary": {
            "cases": len(case_results),
            "rejected": sum(result["decision"] == "REJECT" for result in case_results),
            "human_review_required": sum(
                result["decision"] == "HUMAN_REVIEW_REQUIRED" for result in case_results
            ),
            "pilot_eligible": sum(
                result["decision"] == "PILOT_ELIGIBLE" for result in case_results
            ),
            "total_unsupported_citations": sum(
                int(result["scores"]["hallucination_count"]) for result in case_results
            ),
        },
        "cases": case_results,
        "review_gate": (
            "The certificate evaluates a synthetic benchmark and never authorizes "
            "deployment, contract reliance, or autonomous legal review."
        ),
        "external_actions_allowed": False,
    }
    return {**payload, "integrity_sha256": _canonical_sha256(payload)}


def verify_release_certificate(
    certificate: dict[str, Any],
    case_scores: dict[str, dict[str, Any]],
    *,
    root: Path = Path("."),
) -> dict[str, Any]:
    """Re-evaluate the deterministic suite and verify every certificate field."""

    errors: list[str] = []
    submitted_payload = {
        key: value
        for key, value in certificate.items()
        if key != "integrity_sha256"
    }
    submitted_integrity = str(certificate.get("integrity_sha256", ""))

    # Dispatch by schema. A v1 certificate was issued under the legacy policy and
    # stays verifiable on its own terms; re-deciding it under v2 would rewrite
    # history. An unrecognised schema fails with the value that was seen, because
    # "schema mismatch" alone does not tell a maintainer what to do next.
    schema = certificate.get("schema")
    legacy = schema == LEGACY_SCHEMA
    if schema not in (SCHEMA, LEGACY_SCHEMA):
        # Fail closed and stop. Rebuilding a certificate for an unknown schema would
        # compare a v2 decision against a document this code cannot interpret.
        return {
            "schema": VERIFICATION_SCHEMA,
            "status": "INVALID",
            "errors": [
                f"certificate_schema_unsupported:{schema!r}; "
                f"expected {SCHEMA!r} or {LEGACY_SCHEMA!r}"
            ],
            "verification_sha256": _canonical_sha256({"unsupported_schema": schema}),
        }
    if submitted_integrity != _canonical_sha256(submitted_payload):
        errors.append("certificate_integrity_mismatch")

    if legacy:
        # Verify integrity and inputs only. The legacy decision is not recomputed.
        return {
            "schema": VERIFICATION_SCHEMA,
            "status": "VALID" if not errors else "INVALID",
            "errors": errors,
            "policy": LEGACY_POLICY_ID,
            "legacy_certificate": True,
            "note": (
                "v1 certificate verified for integrity only; its decision was issued "
                "under the legacy policy and is not recomputed under v2"
            ),
            "verification_sha256": _canonical_sha256(
                {"schema": schema, "integrity": submitted_integrity, "errors": errors}
            ),
        }

    expected = build_release_certificate(case_scores, root=root)
    submitted_cases = {
        str(result.get("case")): result
        for result in certificate.get("cases", [])
        if isinstance(result, dict)
    }
    expected_cases = {
        result["case"]: result
        for result in expected["cases"]
    }
    if sorted(submitted_cases) != sorted(expected_cases):
        errors.append("evaluated_case_set_mismatch")
    for case, expected_result in expected_cases.items():
        submitted_result = submitted_cases.get(case)
        if submitted_result is None:
            continue
        if submitted_result.get("input_manifest") != expected_result["input_manifest"]:
            errors.append(f"{case}:input_manifest_mismatch")
        if (
            submitted_result.get("input_manifest_sha256")
            != expected_result["input_manifest_sha256"]
        ):
            errors.append(f"{case}:input_manifest_integrity_mismatch")
        if submitted_result.get("scores") != expected_result["scores"]:
            errors.append(f"{case}:score_reproduction_mismatch")
        if submitted_result.get("decision") != expected_result["decision"]:
            errors.append(f"{case}:decision_mismatch")
        if submitted_result.get("blockers") != expected_result["blockers"]:
            errors.append(f"{case}:blocker_register_mismatch")
        if submitted_result.get("review_items") != expected_result["review_items"]:
            errors.append(f"{case}:review_register_mismatch")

    for field in (
        "policy",
        "suite_decision",
        "summary",
        "review_gate",
        "external_actions_allowed",
    ):
        if certificate.get(field) != expected[field]:
            errors.append(f"{field}_mismatch")

    errors = sorted(set(errors))
    payload = {
        "schema": VERIFICATION_SCHEMA,
        "status": "VALID" if not errors else "INVALID",
        "errors": errors,
        "verified_cases": sorted(expected_cases),
        "certificate_integrity_sha256": submitted_integrity,
        "expected_integrity_sha256": expected["integrity_sha256"],
        "external_actions_allowed": False,
    }
    return {**payload, "verification_sha256": _canonical_sha256(payload)}


def render_release_certificate(certificate: dict[str, Any]) -> str:
    lines = [
        "# Contract Review Release Certificate",
        "",
        f"**Suite decision: {certificate['suite_decision']}**",
        "",
        f"- Policy: `{certificate['policy']['policy_id']}`",
        f"- Cases: {certificate['summary']['cases']}",
        f"- Rejected: {certificate['summary']['rejected']}",
        f"- Unsupported citations: "
        f"{certificate['summary']['total_unsupported_citations']}",
        f"- Integrity SHA-256: `{certificate['integrity_sha256']}`",
        "",
        "## Case decisions",
        "",
        "| Case | Decision | Clause F1 | Risk accuracy | Citation grounding | Unsupported citations |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for result in certificate["cases"]:
        scores = result["scores"]
        lines.append(
            f"| {result['case']} | {result['decision']} | {scores['clause_f1']:.2f} "
            f"| {scores['risk_flag_accuracy']:.2f} | {scores['citation_grounding']:.2f} "
            f"| {scores['hallucination_count']} |"
        )
    lines.extend(["", "## Failure register", ""])
    for result in certificate["cases"]:
        failures = [*result["blockers"], *result["review_items"]]
        lines.append(
            f"- `{result['case']}`: {', '.join(failures) if failures else 'none'}"
        )
    lines.extend(
        [
            "",
            "## Review gate",
            "",
            certificate["review_gate"],
            "",
        ]
    )
    return "\n".join(lines)
