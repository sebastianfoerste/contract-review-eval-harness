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



def _subcommands(parser):
    import argparse

    return next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))


def _listed_commands(parser) -> set[str]:
    return {choice.dest for choice in _subcommands(parser)._choices_actions}


def test_top_level_help_lists_user_commands_and_hides_maintainer_ones():
    from contract_eval.cli import build_parser

    parser = build_parser()
    listed = _listed_commands(parser)
    dev = _subcommands(parser).choices["dev"]

    assert {"evaluate", "certify", "robustness", "score-output", "dev"} <= listed
    maintainer = _listed_commands(dev)
    assert {"verify-certificate", "verify-robustness", "reference-status", "evaluate-obligations"} <= maintainer
    assert not listed & maintainer
    assert "reference-status" not in parser.format_help()


def test_maintainer_commands_run_with_and_without_the_dev_prefix(capsys):
    import json

    from contract_eval.cli import main

    for argv in (
        ["dev", "verify-certificate", "--certificate", "examples/release-certificate.json"],
        ["verify-certificate", "--certificate", "examples/release-certificate.json"],
    ):
        main(argv)
        assert json.loads(capsys.readouterr().out)["status"] == "VALID"
