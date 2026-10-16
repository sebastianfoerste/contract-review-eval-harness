import pytest
from pathlib import Path
from contract_eval.cli import evaluate
from contract_eval.models import ExpectedAnswer

def test_evaluate_gate_passes_by_default(tmp_path):
    # Default nda and saas cases should pass because we calibrated the defaults to the stub
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    assert path.exists()

def test_evaluate_gate_fails_on_unmet_custom_thresholds(tmp_path, monkeypatch):
    # An impossibly high F1 threshold (0.99) must trip the gate.
    expected_data = """{
      "clause_types": ["confidentiality", "definition", "term", "return_destruction", "governing_law"],
      "risk_flags": {
        "term": "high",
        "definition": "medium"
      },
      "severity_rationale": {
        "term": "high because the confidentiality obligation is perpetual",
        "definition": "medium because the definition lacks standard carve-outs"
      },
      "clause_anchors": {
        "confidentiality": "shall keep all Confidential Information secret",
        "definition": "any and all information disclosed by either party",
        "term": "shall remain in effect in perpetuity",
        "return_destruction": "return or destroy all Confidential Information in its possession",
        "governing_law": "laws of the Federal Republic of Germany"
      },
      "thresholds": {
        "f1": 0.99
      }
    }"""
    
    # The case is built in a scratch tree and evaluated from there, because the
    # pipeline reads data/, expected/ and fixtures/ relative to the working directory
    # and the checkout must stay untouched.
    for folder in ("data", "expected", "fixtures"):
        (tmp_path / folder).mkdir()
    (tmp_path / "expected" / "temp_test_case.json").write_text(expected_data)
    (tmp_path / "data" / "temp_test_case_sample.md").write_text(Path("data/nda_sample.md").read_text())
    (tmp_path / "fixtures" / "temp_test_case_stub.json").write_text(Path("fixtures/nda_stub.json").read_text())
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="Evaluation did not meet the required quality thresholds"):
        evaluate(case="temp_test_case", live=False, out_dir=out_dir)

    # Verify that it passes if we specify no_gate=True
    path = evaluate(case="temp_test_case", live=False, out_dir=out_dir, no_gate=True)
    assert path.exists()
