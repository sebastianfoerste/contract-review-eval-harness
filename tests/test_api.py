"""The Python API reaches the CLI's numbers by the CLI's code."""

import json
from pathlib import Path

import pytest

import contract_eval
from contract_eval import (
    ExpectedAnswer,
    ReviewOutput,
    Verdict,
    decide,
    evaluate_review,
    load_case,
    load_review,
    score_review,
)
from contract_eval.api import RESULT_SCHEMA, regression_violations
from contract_eval.capture import canonical_sha256
from contract_eval.cli import evaluate_case
from contract_eval.models import Citation, Clause, RiskFlag

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "fixtures" / "nda_stub.json"


def _oracle(case_name: str = "nda") -> ReviewOutput:
    """A review that restates the answer set and quotes every anchor."""
    gold = load_case(case_name).expected
    return ReviewOutput(
        clauses=[Clause(clause_type=name, text=name) for name in gold.clause_types],
        risk_flags=[
            RiskFlag(clause_type=name, severity=severity, rationale="restated")
            for name, severity in gold.risk_flags.items()
        ],
        citations=[Citation(quote=gold.clause_anchors[name], clause_type=name) for name in gold.clause_types],
    )


def test_the_package_exports_its_api():
    for name in contract_eval.__all__:
        assert hasattr(contract_eval, name), name
    # The CLI keeps re-exporting what used to live there.
    from contract_eval import cli

    assert cli.score_review is score_review


def test_a_bundled_case_records_the_paths_and_digests_the_certificate_uses():
    certificate = json.loads((ROOT / "examples" / "release-certificate.json").read_text())
    manifest = next(r for r in certificate["cases"] if r["case"] == "nda")["input_manifest"]

    case = load_case("nda")

    assert case.bundled
    assert case.source_path == manifest["source_contract"]["path"]
    assert case.source_sha256 == manifest["source_contract"]["sha256"]
    assert case.gold_path == manifest["expected_answer"]["path"]
    assert case.gold_sha256 == manifest["expected_answer"]["sha256"]


def test_scoring_the_stub_through_the_api_matches_evaluate():
    result = evaluate_review(STUB, "nda")

    assert result.scores == evaluate_case("nda", live=False)
    assert result.verdict is Verdict.REJECT
    assert "unsupported_citation_detected" in result.blockers
    assert not result.comparison_only
    assert result.review_path == str(STUB)


def test_a_review_is_accepted_as_a_model_a_dict_or_a_path():
    review, file_sha256 = load_review(STUB)

    from_model = evaluate_review(review, "nda")
    from_dict = evaluate_review(json.loads(STUB.read_text()), "nda")
    from_path = evaluate_review(str(STUB), "nda")

    assert from_model.scores == from_dict.scores == from_path.scores
    assert from_model.review_sha256 == from_dict.review_sha256 == from_path.review_sha256
    assert from_path.review_file_sha256 == file_sha256
    assert from_model.review_file_sha256 is None


def test_a_review_that_restates_the_answer_set_is_pilot_eligible():
    result = evaluate_review(_oracle(), "nda")

    assert result.verdict is Verdict.PILOT_ELIGIBLE
    assert result.blockers == [] and result.review_items == []
    assert result.failures() == []


def test_your_own_contract_and_answer_set_are_comparison_only(tmp_path):
    contract = tmp_path / "contract.md"
    contract.write_text("The agreement is governed by the laws of Ireland.\n", encoding="utf-8")
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({
        "clause_types": ["governing_law"],
        "risk_flags": {"governing_law": "low"},
        "severity_rationale": {"governing_law": "test fixture, no legal judgment intended"},
        "clause_anchors": {"governing_law": "governed by the laws of Ireland"},
    }), encoding="utf-8")
    review = ReviewOutput(
        clauses=[Clause(clause_type="governing_law", text="Irish law")],
        risk_flags=[RiskFlag(clause_type="governing_law", severity="low", rationale="r")],
        citations=[Citation(quote="governed by the laws of Ireland", clause_type="governing_law")],
    )

    case = load_case(contract=contract, gold=gold)
    result = evaluate_review(review, case)

    assert case.name == "gold" and not case.bundled
    assert result.verdict is Verdict.PILOT_ELIGIBLE
    assert result.comparison_only
    payload = result.to_dict()
    assert payload["eligible_for_certification"] is False
    assert payload["inputs"]["source_contract"]["path"] == str(contract)


def test_load_case_names_the_bundled_cases_when_it_cannot_find_one(tmp_path):
    with pytest.raises(ValueError, match="nda, saas, dpa"):
        load_case("lease")
    with pytest.raises(ValueError, match="both contract and gold"):
        load_case(contract=tmp_path / "contract.md")
    with pytest.raises(ValueError):
        load_case()


def test_failures_follow_the_policy_that_was_asked_for():
    rejected = evaluate_review(STUB, "nda")
    assert rejected.failures() == [*rejected.blockers, *rejected.review_items]
    assert rejected.failures(allow_human_review=True), "REJECT always fails the release policy"
    # The stub is calibrated to pass the demo regression gate.
    assert rejected.failures("regression") == []

    review = _oracle().model_copy(update={"risk_flags": []})
    needs_human = evaluate_review(review, "nda")
    assert needs_human.verdict is Verdict.HUMAN_REVIEW_REQUIRED
    assert "expected_risk_missed" in needs_human.failures()
    assert needs_human.failures() == needs_human.review_items
    assert needs_human.failures(allow_human_review=True) == []

    with pytest.raises(ValueError, match="unknown policy"):
        needs_human.failures("lenient")


def test_regression_violations_report_each_threshold_missed():
    scores = evaluate_case("nda", live=False)
    scores = {**scores, "clause_f1": 0.10, "hallucination_count": 3}

    violations = regression_violations("nda", scores)

    assert violations == [
        "[NDA] Clause F1 score 0.10 is below threshold 0.85",
        "[NDA] Hallucination count 3 is above threshold 1",
    ]


def test_decide_returns_the_release_verdict():
    verdict, blockers, _ = decide(evaluate_case("nda", live=False))

    assert verdict is Verdict.REJECT and verdict == "REJECT"
    assert "citation_grounding_below_100_percent" in blockers


def test_the_result_payload_is_sealed_and_deterministic():
    first = evaluate_review(STUB, "nda").to_dict()
    second = evaluate_review(STUB, "nda").to_dict()

    assert first == second
    assert first["schema"] == RESULT_SCHEMA
    body = {k: v for k, v in first.items() if k != "result_sha256"}
    assert first["result_sha256"] == canonical_sha256(body)


def test_score_review_is_still_pure():
    case = load_case("nda")
    review = ReviewOutput.model_validate_json(STUB.read_text())

    assert score_review(case.source_text, case.expected, review) == evaluate_case("nda", live=False)
    assert isinstance(case.expected, ExpectedAnswer)


RAW_OUTPUT = ROOT / "examples" / "raw-output"


def _probe(quote: str) -> dict:
    """Every gold clause and risk named correctly, every citation the same short quote."""
    gold = json.loads((ROOT / "expected" / "nda.json").read_text(encoding="utf-8"))
    return {
        "clauses": [{"clause_type": c, "text": "x"} for c in gold["clause_types"]],
        "risk_flags": [
            {"clause_type": k, "severity": v, "rationale": "x"} for k, v in gold["risk_flags"].items()
        ],
        "citations": [{"quote": quote, "clause_type": c} for c in gold["clause_types"]],
    }


def test_a_one_word_quote_is_grounded_but_rejected_as_degenerate():
    """Grounding is a substring match, so `the` scored 1.0 and was pilot eligible."""
    result = evaluate_review(_probe("the"), "nda")

    assert result.scores["citation_grounding"] == 1.0
    assert result.scores["hallucination_count"] == 0
    assert result.scores["citation_short_count"] == result.scores["citation_total"]
    assert result.verdict is Verdict.REJECT
    assert result.blockers == ["degenerate_citation_detected"]
    assert "risk_flag_without_evidence" in result.review_items
    assert result.scores["risk_flags_without_evidence"] == sorted(load_case("nda").expected.risk_flags)


def test_a_fragment_of_a_word_is_rejected_as_degenerate():
    result = evaluate_review(_probe("confiden"), "nda")

    assert result.scores["hallucination_count"] == 0
    assert result.verdict is Verdict.REJECT
    assert "degenerate_citation_detected" in result.blockers


def test_score_review_checks_evidence_on_the_canonical_clause_name(tmp_path):
    """A flag under a declared synonym is looked up under the gold name's anchor."""
    contract = tmp_path / "contract.md"
    contract.write_text(
        "The agreement is governed by the laws of Ireland. "
        "The supplier may appoint further subcontractors on notice.\n",
        encoding="utf-8",
    )
    gold = tmp_path / "gold.json"
    gold.write_text(json.dumps({
        "clause_types": ["governing_law", "subprocessors"],
        "risk_flags": {"subprocessors": "high"},
        "severity_rationale": {"subprocessors": "test fixture, no legal judgment intended"},
        "clause_aliases": {"sub_processors": "subprocessors"},
        "clause_anchors": {
            "governing_law": "governed by the laws of Ireland",
            "subprocessors": "appoint further subcontractors on notice",
        },
    }), encoding="utf-8")
    review = ReviewOutput(
        clauses=[Clause(clause_type="governing_law", text="x"), Clause(clause_type="sub_processors", text="x")],
        risk_flags=[RiskFlag(clause_type="sub_processors", severity="high", rationale="r")],
        citations=[Citation(quote="governed by the laws of Ireland", clause_type="governing_law")],
    )
    case = load_case(contract=contract, gold=gold)

    with_aliases = evaluate_review(review, case)
    assert with_aliases.scores["risk_flags_without_evidence"] == ["subprocessors"]
    assert with_aliases.verdict is Verdict.HUMAN_REVIEW_REQUIRED
    assert "risk_flag_without_evidence" in with_aliases.review_items

    # Without aliases the flag names no anchored clause, so risk precision carries it.
    without = evaluate_review(review, case, alias_mode="off")
    assert without.scores["risk_flags_without_evidence"] == []
    assert "risk_false_positive" in without.review_items

    quoted = review.model_copy(update={"citations": [
        *review.citations, Citation(quote="appoint further subcontractors", clause_type="sub_processors"),
    ]})
    assert evaluate_review(quoted, case).verdict is Verdict.PILOT_ELIGIBLE


@pytest.mark.parametrize("case", ["nda", "saas", "dpa"])
def test_committed_outputs_keep_their_decisions_under_policy_v2_1(case):
    """The three-word floor clears every committed quote; the stubs gain a review item only."""
    stub = evaluate_review(ROOT / "fixtures" / f"{case}_stub.json", case)
    assert stub.verdict is Verdict.REJECT
    assert stub.scores["citation_short_count"] == 0
    assert stub.blockers == ["citation_grounding_below_100_percent", "unsupported_citation_detected"]
    assert stub.scores["risk_flags_without_evidence"] == {
        "nda": [],
        "saas": ["data_export_on_termination", "indemnity"],
        "dpa": ["audit_rights", "international_transfers"],
    }[case]

    live = evaluate_review(RAW_OUTPUT / f"{case}-claude-opus-5-2026-09-01.json", case)
    assert live.verdict is Verdict.HUMAN_REVIEW_REQUIRED
    assert live.blockers == []
    assert live.scores["citation_short_count"] == 0
    assert live.scores["risk_flags_without_evidence"] == []
    assert "risk_flag_without_evidence" not in live.review_items
