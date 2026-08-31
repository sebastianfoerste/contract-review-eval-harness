from contract_eval.cli import evaluate, evaluate_case


def test_evaluate_writes_scorecard(tmp_path):
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    text = path.read_text()
    assert path.name == "scorecard.md"
    assert "Clause F1" in text
    assert "Hallucination" in text


def test_evaluate_catches_the_seeded_errors(tmp_path):
    # The NDA stub is rigged with a spurious clause, under-rated severities, and one
    # fabricated citation. Assert the properties rather than the decimals, so growing
    # the gold set does not require editing this test.
    scores = evaluate_case("nda", live=False)

    assert scores["clause_recall"] == 1.0, "every expected clause type is found"
    assert scores["clause_precision"] < 1.0, "the spurious clause is penalised"
    assert 0.0 < scores["risk_flag_accuracy"] < 1.0, "some severities are wrong"
    assert scores["hallucination_count"] == 1, "exactly one fabricated citation"
    assert scores["citation_grounding"] < 1.0


def test_evaluate_writes_json_scorecard(tmp_path):
    import json
    path = evaluate(case="nda", live=False, out_dir=tmp_path, format_type="json")
    assert path.name == "scorecard.json"
    data = json.loads(path.read_text())
    assert data["case"] == "nda"
    assert "nda" in data["scores"]
    scores = data["scores"]["nda"]
    assert 0.0 < scores["clause_precision"] < 1.0
    assert 0.0 < scores["risk_flag_accuracy"] < 1.0
    assert 0.0 < scores["citation_grounding"] < 1.0
    assert scores["hallucination_count"] == 1

