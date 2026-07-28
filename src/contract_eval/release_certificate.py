"""Deterministic, input-bound release decisions for a contract-review adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA = "contract-review-eval.release-certificate.v1"
POLICY_ID = "contract-review-eval.strict-legal-release-policy.v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _case_decision(case: str, scores: dict[str, Any], root: Path) -> dict[str, Any]:
    blockers: list[str] = []
    review_items: list[str] = []

    if scores["hallucination_count"] > 0:
        blockers.append("unsupported_citation_detected")
    if scores["citation_grounding"] < 1.0:
        blockers.append("citation_grounding_below_100_percent")
    if scores["clause_recall"] < 1.0:
        review_items.append("expected_clause_missed")
    if scores["clause_precision"] < 1.0:
        review_items.append("unexpected_clause_extracted")
    if scores["risk_flag_accuracy"] < 1.0:
        review_items.append("risk_severity_mismatch")

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
