"""Render an evaluation scorecard as markdown."""

from typing import Any

from contract_eval.scorer import CitationScore, ClauseScore


HUMAN_REVIEW = """## Human review required

This scorecard measures the review method, not a public benchmark. Every flagged risk and
every citation must be confirmed by a qualified lawyer before reliance. A non-zero
hallucination count means at least one citation could not be grounded in the source and
must be rejected outright.
"""


def _risk_rows(s: dict[str, Any]) -> str:
    return (
        f"| Risk precision | {s['risk_precision']:.2f} | flagged clauses that the gold set treats as risks |\n"
        f"| Risk recall | {s['risk_recall']:.2f} | gold risks the review flagged |\n"
        f"| Risk F1 | {s['risk_f1']:.2f} | harmonic mean of risk precision and recall |\n"
        f"| Severity accuracy | {s['risk_severity_accuracy']:.2f} | correct severity among jointly identified risks |\n"
        f"| Risk false positives | {len(s['risk_false_positives'])} | clauses flagged that the gold set does not treat as risks |\n"
        f"| Risk missed | {len(s['risk_missed'])} | gold risks the review did not flag |\n"
        f"| Duplicate / conflicting flags | {len(s['risk_duplicate_flags'])} / {len(s['risk_conflicting_flags'])} | predictions collapsing onto one clause |\n"
        f"| Span coverage | {s['span_coverage']:.2f} | gold clauses with a grounded citation inside them |\n"
    )


def _table(
    clause: ClauseScore,
    risk_accuracy: float,
    citation: CitationScore,
    hallucinations: int,
    risk_rows: str,
) -> str:
    return f"""| Dimension | Score | Notes |
|---|---:|---|
| Clause precision | {clause.precision:.2f} | predicted clause types that were expected |
| Clause recall | {clause.recall:.2f} | expected clause types that were found |
| Clause F1 | {clause.f1:.2f} | harmonic mean of precision and recall |
{risk_rows}| Citation grounding | {citation.grounding_rate:.2f} | {citation.grounded}/{citation.total} quotes matched as an exact span of the normalised source |
| Hallucination count | {hallucinations} | cited quotes not grounded in the source |
| Risk-flag accuracy (legacy) | {risk_accuracy:.2f} | blind to false positives; excluded from release decisions |
"""


def render(
    case: str,
    clause: ClauseScore,
    risk_accuracy: float,
    citation: CitationScore,
    hallucinations: int,
    scores: dict[str, Any] | None = None,
) -> str:
    """Render one case.

    `scores` carries the full metric dict. It is optional so existing callers keep
    working, but without it the risk section cannot be shown, and risk accuracy alone
    is blind to over-flagging.
    """
    s = scores or {}
    risk_rows = _risk_rows(s) if s else ""

    return f"""# Contract Review Eval Scorecard: {case}

## System under review

Adapter output for the `{case}` case, scored against `expected/{case}.json`.

## Scores

{_table(clause, risk_accuracy, citation, hallucinations, risk_rows)}
## Two separate gates

The evaluation threshold gate (`demo-regression-policy.v2`) detects regression against
the deliberately imperfect bundled fixture. Passing it means nothing changed
unexpectedly. It does not mean the output is fit for use.

The release certificate is the eligibility decision. A green CI run is not an approved
benchmark result.

{HUMAN_REVIEW}
## Failure modes checked

- Over-extraction: clause precision below 1.00.
- Missed clause: clause recall below 1.00.
- Over-flagging: risk precision below 1.00.
- Missed risk: risk recall below 1.00.
- Wrong severity: severity accuracy below 1.00.
- Self-contradiction: conflicting flags above 0.
- Fabricated citation: hallucination count above 0.
"""


_DECISION_NOTES = {
    "REJECT": "At least one citation is not an exact span of the contract, which is a hard blocker.",
    "HUMAN_REVIEW_REQUIRED": "No blocker, but at least one requirement is unmet, so a qualified reviewer decides.",
    "PILOT_ELIGIBLE": (
        "Every requirement is met. That supports a supervised pilot at most; it never "
        "authorizes reliance on the review."
    ),
}


def _decision_note(result: dict[str, Any]) -> str:
    # Grounding over zero citations is 0.0, so a review that quotes nothing is rejected
    # without any quote being wrong. Saying a citation failed would misdescribe it.
    if result["decision"] == "REJECT" and result["scores"]["citation_total"] == 0:
        return (
            "The review cites nothing, so none of its findings is grounded in the "
            "contract, which is a hard blocker."
        )
    return _DECISION_NOTES[result["decision"]]


def _codes(items: list[str]) -> str:
    return ", ".join(f"`{item}`" for item in items) if items else "none"


def render_score(result: dict[str, Any]) -> str:
    """Render a `contract-eval score` result: the decision first, then the usual table."""
    s = result["scores"]
    inputs = result["inputs"]
    path = inputs["review_output"]["path"]
    review = f"`{path}`" if path else "The review"
    contract = inputs["source_contract"]["path"]
    gold = inputs["expected_answer"]["path"]
    if result["comparison_only"]:
        subject = f"{review}, scored against your answer set `{gold}` for `{contract}`."
        scope = (
            "\n**Comparison only, not certifiable.** Your contract and answer set go through "
            "the same scorer as the bundled cases, but the harness has not reviewed this "
            "answer set, so the result cannot enter a release certificate.\n"
        )
    else:
        subject = f"{review}, scored against the bundled answer set `{gold}` for `{contract}`."
        scope = ""
    aliases = "applied" if result["alias_mode"] == "on" else "not applied"
    clause = ClauseScore(s["clause_precision"], s["clause_recall"], s["clause_f1"])
    citation = CitationScore(s["citation_grounded"], s["citation_total"], s["citation_grounding"])
    table = _table(clause, s["risk_flag_accuracy"], citation, s["hallucination_count"], _risk_rows(s))
    return f"""# Contract Review Eval Scorecard: {result['case']}

## System under review

{subject} Declared clause aliases {aliases}.
{scope}
## Release decision: {result['decision']}

Policy `{result['policy']}`. {_decision_note(result)}

- Blockers: {_codes(result['blockers'])}
- Review items: {_codes(result['review_items'])}

## Scores

{table}
{HUMAN_REVIEW}"""
