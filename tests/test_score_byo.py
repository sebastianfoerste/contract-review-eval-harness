"""`contract-eval score`: any tool's plain review JSON, a bundled or your own case."""

import json
import shutil
from pathlib import Path

import pytest

from contract_eval import load_case, score_review
from contract_eval.capture import canonical_sha256
from contract_eval.cli import main
from contract_eval.models import Citation, Clause, ReviewOutput, RiskFlag
from contract_eval.schemas import SCHEMAS, schema_document, schema_drift

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "fixtures" / "nda_stub.json"

CONTRACT = """# Consulting Agreement (synthetic)

## 1. Confidentiality
The Consultant shall keep all Client information confidential for five years.

## 2. Termination
Either party may terminate this Agreement on seven days' written notice.
"""

GOLD = {
    "clause_types": ["confidentiality", "termination"],
    "risk_flags": {"termination": "high"},
    "severity_rationale": {"termination": "Seven days leaves no time to replace the consultant."},
    "clause_anchors": {
        "confidentiality": "keep all Client information confidential",
        "termination": "terminate this Agreement on seven days",
    },
}


def _review(**overrides) -> dict:
    review = {
        "clauses": [
            {"clause_type": "confidentiality", "text": "Five-year confidentiality."},
            {"clause_type": "termination", "text": "Short termination notice."},
        ],
        "risk_flags": [{"clause_type": "termination", "severity": "high", "rationale": "short notice"}],
        "citations": [
            {"quote": "keep all Client information confidential for five years", "clause_type": "confidentiality"},
            {"quote": "terminate this Agreement on seven days' written notice", "clause_type": "termination"},
        ],
    }
    review.update(overrides)
    return review


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


@pytest.fixture
def own_case(tmp_path):
    return _write(tmp_path / "msa.md", CONTRACT), _write(tmp_path / "msa.json", GOLD)


def _run(capsys, *argv) -> tuple[int, str, str]:
    try:
        main(["score", *map(str, argv)])
        code = 0
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


def _oracle(case_name: str) -> dict:
    gold = load_case(case_name).expected
    return ReviewOutput(
        clauses=[Clause(clause_type=name, text=name) for name in gold.clause_types],
        risk_flags=[
            RiskFlag(clause_type=name, severity=severity, rationale="restated")
            for name, severity in gold.risk_flags.items()
        ],
        citations=[Citation(quote=gold.clause_anchors[name], clause_type=name) for name in gold.clause_types],
    ).model_dump()


def test_a_fabricated_citation_on_a_bundled_case_rejects_with_exit_1(capsys):
    code, out, _ = _run(capsys, STUB, "--case", "nda")

    assert code == 1
    assert "## Release decision: REJECT" in out
    assert "`unsupported_citation_detected`" in out
    assert "bundled answer set `expected/nda.json`" in out
    assert "Comparison only" not in out


def test_a_review_meeting_every_requirement_exits_0(capsys, tmp_path):
    review = _write(tmp_path / "oracle.json", _oracle("saas"))

    code, out, _ = _run(capsys, review, "--case", "saas")

    assert code == 0
    assert "## Release decision: PILOT_ELIGIBLE" in out


def test_your_own_case_is_scored_but_marked_comparison_only(capsys, own_case, tmp_path):
    contract, gold = own_case
    review = _write(tmp_path / "review.json", _review())

    code, out, _ = _run(capsys, review, "--contract", contract, "--gold", gold, "--format", "json")
    result = json.loads(out)

    assert code == 0
    assert result["case"] == "msa"
    assert result["decision"] == "PILOT_ELIGIBLE"
    assert result["comparison_only"] is True
    assert result["eligible_for_certification"] is False
    assert result["inputs"]["expected_answer"]["path"] == str(gold)

    _, markdown, _ = _run(capsys, review, "--contract", contract, "--gold", gold)
    assert "**Comparison only, not certifiable.**" in markdown
    assert "your answer set" in markdown


def test_the_same_bytes_score_the_same_whether_bundled_or_your_own(capsys, tmp_path):
    shutil.copy(ROOT / "data" / "nda_sample.md", tmp_path / "nda.md")
    shutil.copy(ROOT / "expected" / "nda.json", tmp_path / "nda.json")

    _, bundled, _ = _run(capsys, STUB, "--case", "nda", "--format", "json")
    _, own, _ = _run(
        capsys, STUB, "--contract", tmp_path / "nda.md", "--gold", tmp_path / "nda.json", "--format", "json"
    )
    bundled, own = json.loads(bundled), json.loads(own)

    case = load_case("nda")
    assert bundled["scores"] == own["scores"] == json.loads(json.dumps(
        score_review(case.source_text, case.expected, ReviewOutput.model_validate_json(STUB.read_text()))
    ))
    assert bundled["inputs"]["source_contract"]["sha256"] == own["inputs"]["source_contract"]["sha256"]
    assert (bundled["comparison_only"], own["comparison_only"]) == (False, True)


def test_aliases_off_scores_the_literal_labels(capsys, own_case, tmp_path):
    contract, gold = own_case
    _write(gold, {**GOLD, "clause_aliases": {"term": "termination"}})
    renamed = _review(clauses=[
        {"clause_type": "confidentiality", "text": "Five-year confidentiality."},
        {"clause_type": "term", "text": "Short termination notice."},
    ])
    review = _write(tmp_path / "review.json", renamed)

    _, on, _ = _run(capsys, review, "--contract", contract, "--gold", gold, "--format", "json")
    _, off, _ = _run(capsys, review, "--contract", contract, "--gold", gold, "--format", "json", "--aliases", "off")

    assert json.loads(on)["scores"]["clause_recall"] == 1.0
    assert json.loads(off)["scores"]["clause_recall"] == 0.5
    assert json.loads(off)["alias_mode"] == "off"


def test_fail_on_human_review_tightens_the_gate(capsys, own_case, tmp_path):
    contract, gold = own_case
    # Grounded but under-rated: no blocker, one review item.
    review = _write(tmp_path / "review.json", _review(
        risk_flags=[{"clause_type": "termination", "severity": "low", "rationale": "short notice"}]
    ))

    lenient, out, _ = _run(capsys, review, "--contract", contract, "--gold", gold)
    strict, _, _ = _run(capsys, review, "--contract", contract, "--gold", gold, "--fail-on", "human-review")

    assert "## Release decision: HUMAN_REVIEW_REQUIRED" in out
    assert "`risk_severity_mismatch`" in out
    assert (lenient, strict) == (0, 1)


def test_out_writes_the_scorecard_and_a_sealed_result(capsys, tmp_path):
    code, printed, err = _run(capsys, STUB, "--case", "nda", "--out", tmp_path / "out")

    markdown = (tmp_path / "out" / "score-nda.md").read_text(encoding="utf-8")
    result = json.loads((tmp_path / "out" / "score-nda.json").read_text(encoding="utf-8"))
    assert code == 1
    assert markdown == printed
    assert "wrote" in err
    sealed = result.pop("result_sha256")
    assert sealed == canonical_sha256(result)


@pytest.mark.parametrize(
    ("review", "message"),
    [
        ("{not json", "is not a plain review JSON"),
        (json.dumps({"clauses": []}), "is not a plain review JSON"),
    ],
)
def test_an_unreadable_review_exits_2(capsys, tmp_path, review, message):
    path = _write(tmp_path / "review.json", review)

    code, out, err = _run(capsys, path, "--case", "nda")

    assert code == 2
    assert out == ""
    assert message in err


def test_a_capture_envelope_points_at_score_output(capsys):
    capture = ROOT / "examples" / "captures" / "legacy-nda-2026-09-01.json"

    code, _, err = _run(capsys, capture, "--case", "nda")

    assert code == 2
    assert "contract-eval score-output --input" in err


def test_an_answer_set_breaking_a_cross_field_rule_exits_2(capsys, own_case, tmp_path):
    contract, gold = own_case
    # Valid against the JSON Schema, rejected on load: a risk flag with no rationale.
    _write(gold, {**GOLD, "severity_rationale": {}})
    review = _write(tmp_path / "review.json", _review())

    code, _, err = _run(capsys, review, "--contract", contract, "--gold", gold)

    assert code == 2
    assert "is not a valid answer set" in err
    assert "severity_rationale" in err


def test_a_missing_file_or_unknown_case_exits_2(capsys, tmp_path):
    assert _run(capsys, tmp_path / "absent.json", "--case", "nda")[0] == 2
    code, _, err = _run(capsys, STUB, "--case", "nope")
    assert code == 2
    assert "bundled cases are nda, saas, dpa" in err


@pytest.mark.parametrize(
    "argv",
    [
        (),
        ("--contract", "c.md"),
        ("--case", "nda", "--gold", "g.json"),
    ],
)
def test_the_target_must_be_a_case_or_a_contract_and_gold(capsys, argv):
    code, _, err = _run(capsys, STUB, *argv)

    assert code == 2
    assert "score: pass" in err


def test_the_committed_schemas_match_the_models():
    assert schema_drift(ROOT) == []


def test_schema_drift_is_detected(tmp_path):
    (tmp_path / "schemas").mkdir()
    for name in SCHEMAS:
        shutil.copy(ROOT / "schemas" / name, tmp_path / "schemas" / name)
    review_schema = tmp_path / "schemas" / "review-output.schema.json"
    review_schema.write_text(review_schema.read_text().replace('"clauses"', '"clause_list"'))

    assert schema_drift(tmp_path) == ["schemas/review-output.schema.json"]


def test_the_review_schema_states_what_a_tool_must_produce():
    schema = schema_document("review-output.schema.json")

    assert schema["$id"].endswith("/schemas/review-output.schema.json")
    assert set(schema["required"]) == {"clauses", "risk_flags", "citations"}
    severity = schema["$defs"]["RiskFlag"]["properties"]["severity"]
    assert severity["enum"] == ["low", "medium", "high"]
    # Every bundled fixture is a document the schema describes.
    for fixture in sorted((ROOT / "fixtures").glob("*_stub.json")):
        assert set(schema["required"]) <= set(json.loads(fixture.read_text()))


def test_the_answer_set_schema_names_the_rules_it_cannot_express():
    schema = schema_document("expected-answer.schema.json")

    assert "severity_rationale" in schema["$comment"]
    assert schema["additionalProperties"] is False
