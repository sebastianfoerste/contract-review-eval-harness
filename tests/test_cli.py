import json
from pathlib import Path

import pytest

from contract_eval.cases import ALL_CASES
from contract_eval.cli import compare_runs, evaluate, evaluate_case, main

REGRESSION_BASELINE = Path(__file__).resolve().parents[1] / "examples" / "regression-baseline.json"


def test_evaluate_writes_scorecard(tmp_path):
    path = evaluate(case="nda", live=False, out_dir=tmp_path)
    text = path.read_text()
    assert path.name == "scorecard.md"
    assert "Clause F1" in text
    assert "Hallucination" in text


def test_evaluate_records_history_under_its_output_directory(tmp_path):
    # History written to the working directory polluted the checkout and failed in
    # a read-only tree; the temp_test_case snapshots once committed under history/
    # came from exactly that.
    repo_history = sorted(Path("history").glob("run_*.json"))
    evaluate(case="nda", live=False, out_dir=tmp_path)

    runs = list((tmp_path / "history").glob("run_*.json"))
    assert len(runs) == 1
    assert json.loads(runs[0].read_text())["case"] == "nda"
    assert sorted(Path("history").glob("run_*.json")) == repo_history


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


def _run_file(path: Path, scores: dict[str, dict]) -> Path:
    path.write_text(json.dumps({"case": "all", "scores": scores}))
    return path


def test_compare_reports_a_regression_between_two_recorded_runs(tmp_path):
    current = evaluate_case("nda", live=False)
    better = dict(current, clause_f1=current["clause_f1"] + 0.01)
    baseline = _run_file(tmp_path / "baseline.json", {"nda": better})
    candidate = _run_file(tmp_path / "candidate.json", {"nda": current})

    assert compare_runs(baseline=baseline, candidate=candidate) is True
    assert compare_runs(baseline=candidate, candidate=baseline) is False


def test_compare_counts_one_more_hallucination_as_a_regression(tmp_path):
    current = evaluate_case("nda", live=False)
    worse = dict(current, hallucination_count=current["hallucination_count"] + 1)
    baseline = _run_file(tmp_path / "baseline.json", {"nda": current})
    candidate = _run_file(tmp_path / "candidate.json", {"nda": worse})

    assert compare_runs(baseline=baseline, candidate=candidate) is True


def test_compare_covers_only_the_cases_the_baseline_recorded(tmp_path, capsys):
    nda = evaluate_case("nda", live=False)
    saas = evaluate_case("saas", live=False)
    baseline = _run_file(tmp_path / "baseline.json", {"nda": nda})
    candidate = _run_file(tmp_path / "candidate.json", {"nda": nda, "saas": saas})

    assert compare_runs(baseline=baseline, candidate=candidate) is False
    out = capsys.readouterr().out
    assert "Not in the baseline, so not compared: saas" in out
    assert "Case: SAAS" not in out


def test_compare_refuses_a_candidate_missing_a_baseline_case(tmp_path):
    nda = evaluate_case("nda", live=False)
    baseline = _run_file(tmp_path / "baseline.json", {"nda": nda, "saas": nda})
    candidate = _run_file(tmp_path / "candidate.json", {"nda": nda})

    with pytest.raises(SystemExit) as exit_info:
        compare_runs(baseline=baseline, candidate=candidate)
    assert exit_info.value.code == 1


def test_compare_refuses_to_compare_a_run_with_itself(tmp_path):
    run = _run_file(tmp_path / "run.json", {"nda": evaluate_case("nda", live=False)})

    with pytest.raises(SystemExit) as exit_info:
        compare_runs(baseline=run, candidate=tmp_path / "." / "run.json")
    assert exit_info.value.code == 1


def test_compare_without_paths_scores_current_inputs_against_the_newest_run(tmp_path):
    current = evaluate_case("nda", live=False)
    _run_file(tmp_path / "run_20000101_000000.json", {"nda": current})
    _run_file(tmp_path / "run_20000101_000001.json", {"nda": dict(current, clause_f1=1.0)})

    assert compare_runs(tmp_path) is True


def test_compare_cli_exits_non_zero_on_a_regression(tmp_path):
    current = evaluate_case("nda", live=False)
    baseline = _run_file(tmp_path / "baseline.json", {"nda": dict(current, citation_grounding=1.0)})
    candidate = _run_file(tmp_path / "candidate.json", {"nda": current})

    with pytest.raises(SystemExit) as exit_info:
        main(["compare", "--baseline", str(baseline), "--candidate", str(candidate)])
    assert exit_info.value.code == 1


def test_the_committed_regression_baseline_records_every_case():
    # compare checks only the cases the baseline records, so a case added without
    # `make regression-baseline` would never be compared in CI.
    recorded = json.loads(REGRESSION_BASELINE.read_text(encoding="utf-8"))
    assert recorded["case"] == "all"
    assert sorted(recorded["scores"]) == sorted(ALL_CASES)


def test_the_ci_gate_passes_a_fresh_run_and_fails_a_worse_one(tmp_path):
    # The CI steps in miniature: evaluate into a scratch directory, then compare the
    # run it recorded with the committed baseline.
    evaluate(case="all", live=False, out_dir=tmp_path)
    (fresh,) = (tmp_path / "history").glob("run_*.json")
    gate = ["compare", "--baseline", str(REGRESSION_BASELINE), "--candidate"]

    main([*gate, str(fresh)])

    worse = json.loads(fresh.read_text(encoding="utf-8"))
    worse["scores"]["dpa"]["hallucination_count"] += 1
    doctored = tmp_path / "worse.json"
    doctored.write_text(json.dumps(worse), encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        main([*gate, str(doctored)])
    assert exit_info.value.code == 1


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
