import pytest

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


CASE_COMMANDS = [["evaluate"], ["certify"], ["evaluate-obligations"], ["dev", "evaluate-obligations"]]


@pytest.mark.parametrize("command", CASE_COMMANDS, ids=" ".join)
def test_unknown_case_is_a_usage_error_listing_the_valid_cases(command, capsys):
    from contract_eval.cases import ALL_CASES
    from contract_eval.cli import main

    with pytest.raises(SystemExit) as exited:
        main([*command, "--case", "nope"])

    assert exited.value.code == 2
    err = capsys.readouterr().err
    assert "argument --case: invalid choice: 'nope'" in err
    for name in (*ALL_CASES, "all"):
        assert name in err.split("invalid choice:", 1)[1], f"{name} missing from: {err}"


@pytest.mark.parametrize("command", CASE_COMMANDS, ids=" ".join)
def test_every_bundled_case_is_accepted(command):
    from contract_eval.cases import ALL_CASES
    from contract_eval.cli import build_parser

    for name in (*ALL_CASES, "all"):
        assert build_parser().parse_args([*command, "--case", name]).case == name


def test_evaluate_runs_the_dpa_case(tmp_path, capsys):
    from contract_eval.cli import main

    main(["evaluate", "--case", "dpa", "--out", str(tmp_path)])

    assert "wrote" in capsys.readouterr().out
    assert "# Contract Review Eval Scorecard: dpa" in (tmp_path / "scorecard.md").read_text(encoding="utf-8")


def test_version_prints_the_pyproject_version(capsys):
    import tomllib
    from pathlib import Path

    from contract_eval.cli import main

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    with pytest.raises(SystemExit) as exited:
        main(["--version"])

    assert exited.value.code == 0
    assert capsys.readouterr().out == f"contract-eval {version}\n"


def test_evaluate_reports_errors_on_stderr(monkeypatch, capsys):
    from contract_eval import cli

    def fail(**_kwargs):
        raise ValueError("Evaluation did not meet the required quality thresholds.")

    monkeypatch.setattr(cli, "evaluate", fail)
    with pytest.raises(SystemExit) as exited:
        cli.main(["evaluate", "--case", "nda"])

    assert exited.value.code == 1
    captured = capsys.readouterr()
    assert "Error: Evaluation did not meet the required quality thresholds." in captured.err
    assert "Error:" not in captured.out
