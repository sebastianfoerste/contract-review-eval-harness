"""The v2 evaluation path: contract to evidence-bound score.

Until this existed the v2 stack was unreachable. Gold schema v2, the obligation
scorer, evidence binding and policy v3 were each implemented and tested, and nothing
connected them: no adapter produced an evidence-linked review and no command consumed
one. The pieces worked; the pipeline did not exist.

    contract + v2 gold
            |
            v
    adapter.review_v2  ->  citations with ids, findings referencing them
            |
            v
    bind_review  ->  each finding to one obligation, or unbound
            |
            v
    score_obligations  ->  coverage by evidence, not by label
            |
            v
    policy v3  ->  refuses while the gold is unadjudicated
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract_eval.adapters import get_adapter
from contract_eval.evidence import bind_review
from contract_eval.gold_v2 import ExpectedAnswerV2
from contract_eval.obligation_scorer import score_obligations
from contract_eval.policy_v3 import GoldNotAdjudicated, evaluate_v3

DRAFTS = Path("annotations") / "drafts"


def load_gold_v2(case: str, root: Path = Path(".")) -> ExpectedAnswerV2:
    path = root / DRAFTS / f"{case}.candidate.v2.json"
    gold = ExpectedAnswerV2.model_validate(json.loads(path.read_text(encoding="utf-8")))
    source = (root / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
    gold.validate_against_source(source)
    return gold


def evaluate_obligations(
    case: str,
    *,
    live: bool = False,
    model: str | None = None,
    root: Path = Path("."),
) -> dict[str, Any]:
    """Score one case through the evidence-bound path."""
    source = (root / "data" / f"{case}_sample.md").read_text(encoding="utf-8")
    gold = load_gold_v2(case, root=root)
    review = get_adapter(live, model=model).review_v2(source_text=source, case=case)

    binding = bind_review(source, gold, review)
    coverage = score_obligations(source, gold, review.citations)

    result: dict[str, Any] = {
        "schema": "contract-review-eval.obligation-scorecard.v1",
        "case": case,
        "gold_status": {
            "annotation_status": gold.review_context.annotation_status,
            "adjudication_status": gold.review_context.adjudication_status,
        },
        "obligations": {
            "total": len(gold.obligations),
            "covered": binding.obligation_recall,
            "precision": binding.obligation_precision,
            "uncovered": coverage.uncovered,
        },
        "risk": {
            "precision": binding.risk_precision,
            "recall": binding.risk_recall,
            "severity_accuracy": binding.risk_severity_accuracy,
        },
        "evidence": {
            "unbound_clauses": binding.unbound_clauses,
            "unbound_risks": binding.unbound_risks,
            "unsupported_citations": coverage.unsupported_citations,
            "ambiguous_citations": coverage.ambiguous_citations,
            "unassigned_citations": coverage.unassigned_citations,
            "duplicate_obligation_findings": binding.duplicate_obligation_findings,
            "duplicate_risk_findings": binding.duplicate_risk_findings,
            "conflicting_risk_findings": binding.conflicting_risk_findings,
        },
    }

    try:
        result["certificate"] = evaluate_v3(
            gold, binding, unsupported_citations=coverage.unsupported_citations
        )
    except GoldNotAdjudicated as exc:
        # Expected until a second annotator and adjudication exist. Recorded in the
        # output rather than raised, so the scores stay readable while the decision
        # they would feed stays unavailable.
        result["certificate"] = None
        result["certificate_unavailable"] = str(exc)

    return result


def render(result: dict[str, Any]) -> str:
    obligations, risk, evidence = result["obligations"], result["risk"], result["evidence"]
    lines = [
        f"# Obligation scorecard: {result['case']}",
        "",
        "Scored through cited evidence. Clause and risk labels do not affect these",
        "numbers; where a review quoted does.",
        "",
        "| Dimension | Score |",
        "|---|---:|",
        f"| Obligations | {obligations['total']} |",
        f"| Obligation recall | {obligations['covered']:.3f} |",
        f"| Obligation precision | {obligations['precision']:.3f} |",
        f"| Risk precision | {risk['precision']:.3f} |",
        f"| Risk recall | {risk['recall']:.3f} |",
        f"| Severity accuracy | {risk['severity_accuracy']:.3f} |",
        f"| Unbound clause findings | {len(evidence['unbound_clauses'])} |",
        f"| Unbound risk findings | {len(evidence['unbound_risks'])} |",
        f"| Unsupported citations | {evidence['unsupported_citations']} |",
        f"| Ambiguous citations | {evidence['ambiguous_citations']} |",
        "",
    ]
    if obligations["uncovered"]:
        lines += ["## Obligations with no bound evidence", ""]
        lines += [f"- `{oid}`" for oid in obligations["uncovered"]]
        lines.append("")

    lines += ["## Release decision", ""]
    if result.get("certificate"):
        lines.append(f"**{result['certificate']['decision']}**")
    else:
        lines += [
            "Unavailable.",
            "",
            result["certificate_unavailable"],
            "",
            "The gold set is a single-annotator candidate. Policy v3 refuses to certify",
            "against it, which is why no decision appears here.",
        ]
    lines.append("")
    return "\n".join(lines)
