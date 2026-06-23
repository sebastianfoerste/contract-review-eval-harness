import pytest
from pathlib import Path
from contract_eval.cli import evaluate
from contract_eval.models import ExpectedAnswer

def test_evaluate_gate_passes_by_default(tmp_path):
    # Default nda and saas cases should pass because we calibrated the defaults to the stub
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    assert path.exists()

def test_evaluate_gate_fails_on_unmet_custom_thresholds(tmp_path):
    # Setting an impossibly high F1 threshold (e.g. 0.99) should trigger the gate
    # We will write a custom expected file to tmp_path or mock it.
    # Let's inspect data/nda_sample.md. We can evaluate it but override the expected answer config.
    # To test this simply, we can use a custom case or override the threshold logic.
    # Let's write a mock expected file with high thresholds.
    expected_data = """{
      "clause_types": ["confidentiality", "definition", "term", "return_destruction", "governing_law"],
      "risk_flags": {
        "term": "high",
        "definition": "medium"
      },
      "thresholds": {
        "f1": 0.99
      }
    }"""
    
    # We can temporarily patch the expected file path or just mock the expected file.
    # Let's write a test that forces a violation.
    # We can create a subclass or patch ExpectedAnswer.model_validate to return our high threshold.
    import json
    
    # Let's write a custom JSON file to expected/temp_test_case.json
    expected_file = Path("expected/temp_test_case.json")
    expected_file.write_text(expected_data)

    # Also need a sample markdown file in data/temp_test_case_sample.md
    sample_file = Path("data/temp_test_case_sample.md")
    sample_file.write_text(Path("data/nda_sample.md").read_text())

    # Copy the stub fixture
    fixture_file = Path("fixtures/temp_test_case_stub.json")
    fixture_file.write_text(Path("fixtures/nda_stub.json").read_text())

    try:
        with pytest.raises(ValueError, match="Evaluation did not meet the required quality thresholds"):
            evaluate(case="temp_test_case", live=False, out_dir=tmp_path)
            
        # Verify that it passes if we specify no_gate=True
        path = evaluate(case="temp_test_case", live=False, out_dir=tmp_path, no_gate=True)
        assert path.exists()
    finally:
        # Clean up files
        if expected_file.exists():
            expected_file.unlink()
        if sample_file.exists():
            sample_file.unlink()
        if fixture_file.exists():
            fixture_file.unlink()
