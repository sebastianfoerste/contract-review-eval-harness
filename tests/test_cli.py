from contract_eval.cli import evaluate


def test_evaluate_writes_scorecard(tmp_path):
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    text = path.read_text()
    assert path.name == "scorecard.md"
    assert "Clause F1" in text
    assert "Hallucination" in text


def test_evaluate_catches_the_seeded_errors(tmp_path):
    # The NDA stub is rigged with a spurious clause, a wrong severity, and one
    # fabricated citation. The harness must surface all three.
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    text = path.read_text()
    assert "0.83" in text  # clause precision: 5 of 6 predicted clause types are expected
    assert "0.50" in text  # risk-flag accuracy: 1 of 2 severities correct
    assert "0.80" in text  # citation grounding: 4 of 5 quotes grounded


def test_evaluate_writes_json_scorecard(tmp_path):
    import json
    path = evaluate(case="nda", live=False, out_dir=tmp_path, format_type="json")
    assert path.name == "scorecard.json"
    data = json.loads(path.read_text())
    assert data["case"] == "nda"
    assert "nda" in data["scores"]
    scores = data["scores"]["nda"]
    assert scores["clause_precision"] == 0.8333333333333334 or round(scores["clause_precision"], 2) == 0.83
    assert scores["risk_flag_accuracy"] == 0.5
    assert scores["citation_grounding"] == 0.8
    assert scores["hallucination_count"] == 1

