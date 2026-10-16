"""The Python API: load a case, score a review, decide under the release policy.

The CLI, the pytest plugin and a notebook all reach their numbers through these
functions, so a score printed by one is a score the others reproduce.

    case = load_case("nda")                    # or load_case(contract=..., gold=...)
    result = evaluate_review(review, case)     # review: ReviewOutput, dict or JSON path
    result.verdict                             # Verdict.REJECT
    result.scores["citation_grounding"]        # 0.888...

A bundled case is scored against the reviewed answer set the release certificate
uses. Your own contract and answer set are scored by the same code, and the result is
marked comparison-only: the harness cannot vouch for an answer set it did not review.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Any

from contract_eval import paths
from contract_eval.capture import canonical_sha256, text_sha256
from contract_eval.cases import ALL_CASES
from contract_eval.models import ExpectedAnswer, ReviewOutput
from contract_eval.release_certificate import POLICY_ID, case_decision
from contract_eval.scorer import (
    citation_grounding,
    clause_scores,
    count_hallucinations,
    risk_flag_accuracy,
    risk_metrics,
    span_coverage,
)

RESULT_SCHEMA = "contract-review-eval.score-result.v1"
REGRESSION_POLICY_ID = "demo-regression-policy.v2"
POLICIES: tuple[str, ...] = ("release", "regression")


class Verdict(StrEnum):
    """The release policy's three outcomes, worst first."""

    REJECT = "REJECT"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    PILOT_ELIGIBLE = "PILOT_ELIGIBLE"


def canonical_clause(clause_type: str, aliases: dict[str, str]) -> str:
    """Map a declared synonym onto the gold set's own name for the same clause.

    Adapters name clauses in their own vocabulary: `no_licence` for `no_license`,
    `sub_processors` for `subprocessors`, `permitted_disclosures` for the singular.
    Scoring those as missed clauses measures vocabulary, not legal judgment, and
    quietly reports a correct review as a failure. Aliases are declared in the gold
    set so the mapping is reviewable.
    """
    return aliases.get(clause_type, clause_type)


def canonicalise_risk_flags(
    risk_flags: list,
    aliases: dict[str, str],
) -> tuple[dict[str, str], list[str], list[str]]:
    """Collapse predicted flags onto canonical clause names, visibly.

    A dict comprehension silently kept the last flag whenever two predictions
    canonicalised onto the same clause, so a review flagging `sub_processors` high
    and `subprocessors` low scored as whichever came second. Duplicates are now
    reported, and a duplicate carrying a different severity is a conflict: the
    review contradicts itself about one clause and cannot be treated as agreeing
    with the gold set.
    """
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []
    for flag in risk_flags:
        canonical = canonical_clause(flag.clause_type, aliases)
        if canonical in seen:
            duplicates.append(canonical)
            if seen[canonical] != flag.severity:
                conflicts.append(canonical)
            continue
        seen[canonical] = flag.severity
    return seen, sorted(set(duplicates)), sorted(set(conflicts))


def score_review(
    source_text: str,
    expected: ExpectedAnswer,
    output: ReviewOutput,
    *,
    alias_mode: str = "on",
) -> dict:
    """Score one review. Pure: no file access, no network, no adapter.

    Extracted so a live evaluation and an offline replay of the same captured bytes
    run through identical code. If replay had its own scoring path, a replayed score
    would prove nothing about the published one.

    `alias_mode` selects whether declared clause synonyms are applied, which is what
    makes the aliases-off and aliases-on comparison a controlled experiment rather
    than two different scorers.
    """
    if alias_mode not in ("on", "off"):
        raise ValueError(f"alias_mode must be 'on' or 'off', got {alias_mode!r}")
    aliases = expected.clause_aliases if alias_mode == "on" else {}
    source = source_text
    clause = clause_scores(
        expected.clause_types,
        [canonical_clause(c.clause_type, aliases) for c in output.clauses],
    )
    predicted_flags, duplicate_flags, conflicting_flags = canonicalise_risk_flags(
        output.risk_flags, aliases
    )
    risk_accuracy = risk_flag_accuracy(expected.risk_flags, predicted_flags)
    risk = risk_metrics(expected.risk_flags, predicted_flags)
    citation = citation_grounding(source, output.citations)
    hallucinations = count_hallucinations(source, output.citations)
    coverage = span_coverage(source, expected.clause_anchors, output.citations)

    # Base thresholds matching the stub adapter baseline
    thresholds = {
        "f1": 0.85,
        "risk_accuracy": 0.45,
        "grounding_rate": 0.75,
        "hallucinations": 1.0,
    }
    if expected.thresholds:
        thresholds.update(expected.thresholds)

    return {
        "clause_precision": clause.precision,
        "clause_recall": clause.recall,
        "clause_f1": clause.f1,
        "risk_flag_accuracy": risk_accuracy,
        "risk_precision": risk.precision,
        "risk_recall": risk.recall,
        "risk_f1": risk.f1,
        "risk_severity_accuracy": risk.severity_accuracy,
        "risk_false_positives": risk.false_positives,
        "risk_missed": risk.missed,
        "risk_severity_confusion": risk.severity_confusion,
        "risk_duplicate_flags": duplicate_flags,
        "risk_conflicting_flags": conflicting_flags,
        "span_coverage": coverage.coverage,
        "span_uncovered_clauses": coverage.uncovered,
        "citation_grounded": citation.grounded,
        "citation_total": citation.total,
        "citation_grounding": citation.grounding_rate,
        "hallucination_count": hallucinations,
        "thresholds": thresholds,
    }


def regression_violations(case: str, scores: dict[str, Any]) -> list[str]:
    """Where a case falls below the demo regression thresholds.

    This gate is calibrated to the deliberately imperfect stub, so it detects change
    rather than fitness. The release policy is the eligibility decision.
    """
    t = scores["thresholds"]
    label = case.upper()
    violations = []
    if scores["clause_f1"] < t["f1"]:
        violations.append(f"[{label}] Clause F1 score {scores['clause_f1']:.2f} is below threshold {t['f1']:.2f}")
    if scores["risk_flag_accuracy"] < t["risk_accuracy"]:
        violations.append(f"[{label}] Risk-flag accuracy {scores['risk_flag_accuracy']:.2f} is below threshold {t['risk_accuracy']:.2f}")
    if scores["citation_grounding"] < t["grounding_rate"]:
        violations.append(f"[{label}] Citation grounding rate {scores['citation_grounding']:.2f} is below threshold {t['grounding_rate']:.2f}")
    if float(scores["hallucination_count"]) > t["hallucinations"]:
        violations.append(f"[{label}] Hallucination count {scores['hallucination_count']} is above threshold {t['hallucinations']:.0f}")
    return violations


@dataclass(frozen=True)
class Case:
    """One contract and the answer set it is scored against.

    `bundled` is true only for a case in the evaluated suite, read from the case
    root. Paths and digests record what was read, so a result names its inputs.
    """

    name: str
    source_text: str
    expected: ExpectedAnswer
    source_path: str | None = None
    gold_path: str | None = None
    source_sha256: str | None = None
    gold_sha256: str | None = None
    bundled: bool = False


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> tuple[str, str]:
    """Text as every other entry point reads it, and the file's SHA-256."""
    return path.read_text(encoding="utf-8"), _sha256(path.read_bytes())


def load_case(
    name: str | None = None,
    *,
    contract: str | PathLike[str] | None = None,
    gold: str | PathLike[str] | None = None,
    root: Path | None = None,
) -> Case:
    """Load a bundled case by name, or your own contract and answer set.

    `load_case("nda")` reads the bundled NDA. `load_case(contract="msa.md",
    gold="msa.json")` reads yours; `name` then only labels the result and defaults to
    the answer set's file name.
    """
    if contract is not None or gold is not None:
        if contract is None or gold is None:
            raise ValueError("pass both contract and gold, or a bundled case name")
        source_text, source_sha256 = _read(Path(contract))
        gold_text, gold_sha256 = _read(Path(gold))
        return Case(
            name=name or Path(gold).stem,
            source_text=source_text,
            expected=ExpectedAnswer.model_validate_json(gold_text),
            source_path=str(contract),
            gold_path=str(gold),
            source_sha256=source_sha256,
            gold_sha256=gold_sha256,
            bundled=False,
        )
    if name is None:
        raise ValueError("pass a bundled case name, or both contract and gold")
    if name not in ALL_CASES:
        raise ValueError(f"unknown case {name!r}; bundled cases are {', '.join(ALL_CASES)}")
    root = paths.resolve_root(root)
    source_text, source_sha256 = _read(root / paths.source_file(name))
    gold_text, gold_sha256 = _read(root / paths.gold_file(name))
    return Case(
        name=name,
        source_text=source_text,
        expected=ExpectedAnswer.model_validate_json(gold_text),
        source_path=paths.source_file(name),
        gold_path=paths.gold_file(name),
        source_sha256=source_sha256,
        gold_sha256=gold_sha256,
        bundled=True,
    )


def load_review(path: str | PathLike[str]) -> tuple[ReviewOutput, str]:
    """Read a plain ReviewOutput JSON file; returns the review and the file's SHA-256."""
    data = Path(path).read_bytes()
    return ReviewOutput.model_validate_json(data), _sha256(data)


@dataclass(frozen=True)
class ReviewResult:
    """A scored review and its release decision."""

    case: Case
    scores: dict[str, Any]
    verdict: Verdict
    blockers: list[str]
    review_items: list[str]
    alias_mode: str
    review_sha256: str
    review_path: str | None = None
    review_file_sha256: str | None = None

    @property
    def comparison_only(self) -> bool:
        """True unless the case is bundled: the same rule replay applies to drifted inputs."""
        return not self.case.bundled

    def failures(self, policy: str = "release", *, allow_human_review: bool = False) -> list[str]:
        """Why this result fails `policy`; empty when it passes.

        `release` passes only a PILOT_ELIGIBLE review, or with `allow_human_review`
        anything short of REJECT. `regression` applies the demo thresholds that
        `contract-eval evaluate` gates on.
        """
        if policy == "release":
            if self.verdict is Verdict.REJECT:
                return [*self.blockers, *self.review_items]
            if self.verdict is Verdict.HUMAN_REVIEW_REQUIRED and not allow_human_review:
                return list(self.review_items)
            return []
        if policy == "regression":
            return regression_violations(self.case.name, self.scores)
        raise ValueError(f"unknown policy {policy!r}; expected one of {', '.join(POLICIES)}")

    def to_dict(self) -> dict[str, Any]:
        """The JSON result `contract-eval score` writes, sealed with its own digest."""
        payload = {
            "schema": RESULT_SCHEMA,
            "case": self.case.name,
            "policy": POLICY_ID,
            "decision": str(self.verdict),
            "blockers": list(self.blockers),
            "review_items": list(self.review_items),
            "comparison_only": self.comparison_only,
            "eligible_for_certification": not self.comparison_only,
            "alias_mode": self.alias_mode,
            "inputs": {
                "source_contract": {"path": self.case.source_path, "sha256": self.case.source_sha256},
                "expected_answer": {"path": self.case.gold_path, "sha256": self.case.gold_sha256},
                "review_output": {
                    "path": self.review_path,
                    "sha256": self.review_file_sha256,
                    "parsed_sha256": self.review_sha256,
                },
            },
            "scores": self.scores,
        }
        return {**payload, "result_sha256": canonical_sha256(payload)}


def decide(scores: dict[str, Any]) -> tuple[Verdict, list[str], list[str]]:
    """Apply the release policy to one case's scores: (verdict, blockers, review items)."""
    decision, blockers, review_items = case_decision(scores)
    return Verdict(decision), blockers, review_items


def evaluate_review(
    review: ReviewOutput | dict[str, Any] | str | PathLike[str],
    case: Case | str,
    *,
    alias_mode: str = "on",
) -> ReviewResult:
    """Score a review against a case and decide it under the release policy.

    `review` is a ReviewOutput, a dict of the same shape, or a path to its JSON.
    `case` is a Case from `load_case`, or a bundled case name.
    """
    if isinstance(case, str):
        case = load_case(case)
    review_path = review_file_sha256 = None
    if isinstance(review, (str, PathLike)):
        review_path = str(review)
        review, review_file_sha256 = load_review(review)
    elif isinstance(review, dict):
        review = ReviewOutput.model_validate(review)
    scores = score_review(case.source_text, case.expected, review, alias_mode=alias_mode)
    verdict, blockers, review_items = decide(scores)
    return ReviewResult(
        case=case,
        scores=scores,
        verdict=verdict,
        blockers=blockers,
        review_items=review_items,
        alias_mode=alias_mode,
        review_sha256=text_sha256(review.model_dump_json()),
        review_path=review_path,
        review_file_sha256=review_file_sha256,
    )


def write_result(result: ReviewResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
