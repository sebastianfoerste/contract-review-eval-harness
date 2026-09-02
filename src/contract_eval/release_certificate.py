"""Deterministic, input-bound release decisions for a contract-review adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, NamedTuple

SCHEMA = "contract-review-eval.release-certificate.v3"
V2_SCHEMA = "contract-review-eval.release-certificate.v2"
V1_SCHEMA = "contract-review-eval.release-certificate.v1"
# Schema v3 corrects the artifact shape. The policy it publishes is unchanged.
POLICY_ID = "contract-review-eval.strict-legal-release-policy.v2"
LEGACY_POLICY_ID = "contract-review-eval.strict-legal-release-policy.v1"
VERIFICATION_SCHEMA = "contract-review-eval.release-certificate-verification.v1"


class Requirement(NamedTuple):
    """One condition a case must satisfy to remain eligible.

    The registry below is the single source of truth for the release decision, the
    policy metadata the certificate publishes, which scores appear in each case, and
    what the verifier expects. Before v3 those four drifted apart: the decision read
    risk precision, risk recall, severity accuracy and the duplicate and conflicting
    flag lists, while the published artifact advertised a `risk_flag_accuracy_target`
    that no longer decided anything and omitted every metric that did. A reader could
    not reconstruct the decision from the certificate.
    """

    requirement_id: str
    metric: str
    comparator: str  # gte | lte | zero | empty
    threshold: float | None
    failure_class: str  # blocker | review_item
    failure_code: str
    description: str


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "citation.grounding", "citation_grounding", "gte", 1.0, "blocker",
        "citation_grounding_below_100_percent",
        "Every citation must match an exact span of the normalised source.",
    ),
    Requirement(
        "citation.unsupported", "hallucination_count", "zero", None, "blocker",
        "unsupported_citation_detected",
        "No citation may be unsupported by the source document.",
    ),
    Requirement(
        "clause.precision", "clause_precision", "gte", 1.0, "review_item",
        "unexpected_clause_extracted",
        "No clause may be reported that the gold set does not declare.",
    ),
    Requirement(
        "clause.recall", "clause_recall", "gte", 1.0, "review_item",
        "expected_clause_missed",
        "Every gold clause must be found.",
    ),
    Requirement(
        "risk.precision", "risk_precision", "gte", 1.0, "review_item",
        "risk_false_positive",
        "No clause may be flagged that the gold set does not treat as a risk.",
    ),
    Requirement(
        "risk.recall", "risk_recall", "gte", 1.0, "review_item",
        "expected_risk_missed",
        "Every gold risk must be flagged.",
    ),
    Requirement(
        "risk.severity", "risk_severity_accuracy", "gte", 1.0, "review_item",
        "risk_severity_mismatch",
        "Every jointly identified risk must carry the gold severity.",
    ),
    Requirement(
        "risk.duplicates", "risk_duplicate_flags", "empty", None, "review_item",
        "duplicate_risk_flags",
        "No two predictions may collapse onto one clause.",
    ),
    Requirement(
        "risk.conflicts", "risk_conflicting_flags", "empty", None, "review_item",
        "conflicting_risk_flags",
        "One clause may not carry contradictory severities.",
    ),
)

# Published beside the decision inputs, clearly separated. These inform a reader and
# never change eligibility. Legacy risk-flag accuracy lives here because it is blind
# to false positives and must not be mistaken for a decision input.
DIAGNOSTIC_METRICS: tuple[str, ...] = (
    "clause_f1",
    "risk_f1",
    "risk_flag_accuracy",
    "risk_false_positives",
    "risk_missed",
    "risk_severity_confusion",
    "span_coverage",
    "span_uncovered_clauses",
    "citation_grounded",
    "citation_total",
)


def _satisfied(requirement: Requirement, value: Any) -> bool:
    if requirement.comparator == "gte":
        return float(value) >= float(requirement.threshold)
    if requirement.comparator == "lte":
        return float(value) <= float(requirement.threshold)
    if requirement.comparator == "zero":
        return float(value) == 0.0
    if requirement.comparator == "empty":
        return not value
    raise ValueError(f"unknown comparator: {requirement.comparator}")


def evaluate_requirements(scores: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (blockers, review_items) for one case, driven by the registry."""
    blockers: list[str] = []
    review_items: list[str] = []
    for requirement in REQUIREMENTS:
        if requirement.metric not in scores:
            raise KeyError(
                f"score {requirement.metric!r} is required by {requirement.requirement_id!r} "
                "but was not supplied; a certificate cannot omit a decision input"
            )
        if _satisfied(requirement, scores[requirement.metric]):
            continue
        if requirement.failure_class == "blocker":
            blockers.append(requirement.failure_code)
        else:
            review_items.append(requirement.failure_code)
    return blockers, review_items


def policy_metadata() -> dict[str, Any]:
    """Publish the policy exactly as the registry enforces it."""
    return {
        "policy_id": POLICY_ID,
        "requirements": [
            {
                "requirement_id": r.requirement_id,
                "metric": r.metric,
                "comparator": r.comparator,
                "threshold": r.threshold,
                "failure_class": r.failure_class,
                "failure_code": r.failure_code,
                "description": r.description,
            }
            for r in REQUIREMENTS
        ],
        "hard_blockers": [r.failure_code for r in REQUIREMENTS if r.failure_class == "blocker"],
        "diagnostics_only": list(DIAGNOSTIC_METRICS),
    }



def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _case_decision(case: str, scores: dict[str, Any], root: Path) -> dict[str, Any]:
    blockers, review_items = evaluate_requirements(scores)

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
        # Every metric the decision reads, selected from the registry so the two
        # cannot drift apart again.
        "scores": {r.metric: scores[r.metric] for r in REQUIREMENTS},
        "diagnostics": {
            metric: scores[metric] for metric in DIAGNOSTIC_METRICS if metric in scores
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
        "policy": policy_metadata(),
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

    # Dispatch by schema, and publish the scope actually achieved. A historical
    # certificate must stay checkable without being re-decided under a policy that
    # did not exist when it was issued; silently re-deciding it would falsify the
    # record. `verification_scope` states which of those happened.
    schema = certificate.get("schema")
    known = (SCHEMA, V2_SCHEMA, V1_SCHEMA)
    if schema not in known:
        # Fail closed and stop. Rebuilding a certificate for an unknown schema would
        # compare a current decision against a document this code cannot interpret.
        return {
            "schema": VERIFICATION_SCHEMA,
            "status": "INVALID",
            "verification_scope": "none",
            "errors": [
                f"certificate_schema_unsupported:{schema!r}; expected one of {known!r}"
            ],
            "verification_sha256": _canonical_sha256({"unsupported_schema": schema}),
        }

    if submitted_integrity != _canonical_sha256(submitted_payload):
        errors.append("certificate_integrity_mismatch")

    if schema == V1_SCHEMA:
        payload = {
            "schema": VERIFICATION_SCHEMA,
            "status": "VALID" if not errors else "INVALID",
            "verification_scope": "integrity_only",
            "errors": errors,
            "policy": LEGACY_POLICY_ID,
            "certificate_schema": schema,
            "note": (
                "v1 certificate verified for integrity only; its decision was issued "
                "under the legacy policy and is not recomputed"
            ),
            "external_actions_allowed": False,
        }
        return {**payload, "verification_sha256": _canonical_sha256(payload)}

    if schema == V2_SCHEMA:
        # A v2 certificate is reproduced by the frozen v2 builder while its inputs
        # still match. Once an input has moved, the historical decision can no longer
        # be recomputed against it, so verification degrades to integrity only and
        # says so rather than reporting a mismatch the reader cannot act on.
        drift = _input_drift(certificate, root=root)
        if drift:
            payload = {
                "schema": VERIFICATION_SCHEMA,
                "status": "VALID" if not errors else "INVALID",
                "verification_scope": "integrity_only",
                "errors": errors,
                "certificate_schema": schema,
                "input_drift": drift,
                "note": (
                    "v2 certificate inputs have changed since issue, so the historical "
                    "decision was not recomputed; re-issue under the current schema to "
                    "regain a current eligibility decision"
                ),
                "external_actions_allowed": False,
            }
            return {**payload, "verification_sha256": _canonical_sha256(payload)}
        expected = _build_v2_certificate(case_scores, root=root)
        return _compare(certificate, expected, errors, submitted_integrity, "full_v2")

    expected = build_release_certificate(case_scores, root=root)
    return _compare(certificate, expected, errors, submitted_integrity, "full")


def _compare(
    certificate: dict[str, Any],
    expected: dict[str, Any],
    errors: list[str],
    submitted_integrity: str,
    scope: str,
) -> dict[str, Any]:
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
        "verification_scope": scope,
        "errors": errors,
        "verified_cases": sorted(expected_cases),
        "certificate_integrity_sha256": submitted_integrity,
        "expected_integrity_sha256": expected["integrity_sha256"],
        "external_actions_allowed": False,
    }
    return {**payload, "verification_sha256": _canonical_sha256(payload)}


def _input_drift(certificate: dict[str, Any], *, root: Path) -> list[str]:
    """Name every case whose recorded inputs no longer match the working tree."""
    drift: list[str] = []
    for result in certificate.get("cases", []):
        if not isinstance(result, dict):
            continue
        case = str(result.get("case"))
        manifest = result.get("input_manifest")
        if not isinstance(manifest, dict):
            drift.append(f"{case}:input_manifest_absent")
            continue
        for label, entry in sorted(manifest.items()):
            if not isinstance(entry, dict):
                continue
            path = root / str(entry.get("path", ""))
            if not path.is_file():
                drift.append(f"{case}:{label}:missing")
            elif _sha256(path) != entry.get("sha256"):
                drift.append(f"{case}:{label}:changed")
    return sorted(drift)


def _build_v2_certificate(
    case_scores: dict[str, dict[str, Any]],
    *,
    root: Path = Path("."),
) -> dict[str, Any]:
    """Frozen v2 builder, retained so v2 certificates stay reproducible.

    This is deliberately a copy rather than a call into the current builder. The
    current builder publishes the v3 artifact shape; reproducing a v2 certificate
    with it would report a mismatch on every case for a document that was correct
    when it was issued.
    """
    if not case_scores:
        raise ValueError("release certificate requires at least one evaluated case")

    case_results = []
    for case in sorted(case_scores):
        scores = case_scores[case]
        blockers, review_items = evaluate_requirements(scores)
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
        case_results.append({
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
        })

    decisions = {result["decision"] for result in case_results}
    if "REJECT" in decisions:
        suite_decision = "REJECT"
    elif "HUMAN_REVIEW_REQUIRED" in decisions:
        suite_decision = "HUMAN_REVIEW_REQUIRED"
    else:
        suite_decision = "PILOT_ELIGIBLE"

    payload = {
        "schema": V2_SCHEMA,
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
            "rejected": sum(r["decision"] == "REJECT" for r in case_results),
            "human_review_required": sum(
                r["decision"] == "HUMAN_REVIEW_REQUIRED" for r in case_results
            ),
            "pilot_eligible": sum(r["decision"] == "PILOT_ELIGIBLE" for r in case_results),
            "total_unsupported_citations": sum(
                int(r["scores"]["hallucination_count"]) for r in case_results
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
        "Every column below is a decision input. A case is eligible only when all of",
        "them pass; diagnostics are reported separately and never decide anything.",
        "",
        "| Case | Decision | "
        + " | ".join(r.requirement_id for r in REQUIREMENTS)
        + " |",
        "| --- | --- | " + " | ".join("---:" for _ in REQUIREMENTS) + " |",
    ]
    for result in certificate["cases"]:
        scores = result["scores"]
        cells = []
        for requirement in REQUIREMENTS:
            value = scores[requirement.metric]
            if isinstance(value, list):
                cells.append(str(len(value)))
            elif isinstance(value, float):
                cells.append(f"{value:.2f}")
            else:
                cells.append(str(value))
        lines.append(
            f"| {result['case']} | {result['decision']} | " + " | ".join(cells) + " |"
        )

    lines.extend(["", "## Diagnostics (not decision inputs)", ""])
    diagnostic_keys = [
        key for key in DIAGNOSTIC_METRICS
        if any(key in result.get("diagnostics", {}) for result in certificate["cases"])
    ]
    if diagnostic_keys:
        lines.append("| Case | " + " | ".join(diagnostic_keys) + " |")
        lines.append("| --- | " + " | ".join("---:" for _ in diagnostic_keys) + " |")
        for result in certificate["cases"]:
            diagnostics = result.get("diagnostics", {})
            cells = []
            for key in diagnostic_keys:
                value = diagnostics.get(key)
                if isinstance(value, (list, dict)):
                    cells.append(str(len(value)))
                elif isinstance(value, float):
                    cells.append(f"{value:.2f}")
                else:
                    cells.append(str(value))
            lines.append(f"| {result['case']} | " + " | ".join(cells) + " |")

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
