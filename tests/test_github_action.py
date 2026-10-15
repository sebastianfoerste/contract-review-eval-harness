"""The GitHub Action's scoring step, run as the composite action runs it."""

import json
import re
import shutil
from pathlib import Path

import pytest

from contract_eval import load_case
from contract_eval.github_action import result_stem, review_files, run

ROOT = Path(__file__).resolve().parents[1]
STUB = ROOT / "fixtures" / "nda_stub.json"


def _oracle(case_name: str) -> dict:
    gold = load_case(case_name).expected
    return {
        "clauses": [{"clause_type": name, "text": name} for name in gold.clause_types],
        "risk_flags": [
            {"clause_type": name, "severity": severity, "rationale": "restated"}
            for name, severity in gold.risk_flags.items()
        ],
        "citations": [
            {"quote": gold.clause_anchors[name], "clause_type": name} for name in gold.clause_types
        ],
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reviews").mkdir()
    return tmp_path


def _env(workspace: Path, **inputs) -> dict[str, str]:
    env = {
        "GITHUB_STEP_SUMMARY": str(workspace / "summary.md"),
        "GITHUB_OUTPUT": str(workspace / "output"),
        "INPUT_REVIEWS": "reviews/*.json",
        "INPUT_CASE": "nda",
        "INPUT_CONTRACT": "",
        "INPUT_GOLD": "",
        "INPUT_ALIASES": "on",
        "INPUT_FAIL_ON": "reject",
        "INPUT_OUT": "results",
    }
    env.update({f"INPUT_{key.upper()}": value for key, value in inputs.items()})
    return env


def _outputs(workspace: Path) -> dict[str, str]:
    lines = (workspace / "output").read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", 1) for line in lines)


def test_a_rejected_review_fails_the_step_and_reports_why(workspace, capsys):
    shutil.copy(STUB, workspace / "reviews" / "vendor.json")

    status = run(_env(workspace))

    assert status == 1
    assert "::error file=reviews/vendor.json::REJECT: citation_grounding_below_100_percent" in capsys.readouterr().out
    assert _outputs(workspace) == {"decision": "REJECT", "results-dir": "results"}
    summary = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "| `reviews/vendor.json` | nda | **REJECT** | 0.96 | 0.83 | 0.89 | 1 |" in summary
    assert "## Release decision: REJECT" in summary
    result = json.loads((workspace / "results" / "reviews__vendor.json").read_text(encoding="utf-8"))
    assert result["decision"] == "REJECT"
    assert (workspace / "results" / "reviews__vendor.md").read_text(encoding="utf-8").startswith("# Contract")


def test_the_worst_decision_wins_and_a_passing_review_alone_passes(workspace):
    (workspace / "reviews" / "good.json").write_text(json.dumps(_oracle("nda")), encoding="utf-8")

    assert run(_env(workspace)) == 0
    assert _outputs(workspace)["decision"] == "PILOT_ELIGIBLE"

    shutil.copy(STUB, workspace / "reviews" / "bad.json")
    (workspace / "output").unlink()

    assert run(_env(workspace)) == 1
    assert _outputs(workspace)["decision"] == "REJECT"


def test_fail_on_human_review_fails_a_review_that_needs_a_human(workspace):
    review = _oracle("nda")
    flagged = review["risk_flags"][0]
    flagged["severity"] = "low" if flagged["severity"] != "low" else "high"
    (workspace / "reviews" / "underrated.json").write_text(json.dumps(review), encoding="utf-8")

    assert run(_env(workspace)) == 0
    assert _outputs(workspace)["decision"] == "HUMAN_REVIEW_REQUIRED"
    assert run(_env(workspace, fail_on="human-review")) == 1


def test_your_own_answer_set_is_flagged_comparison_only(workspace):
    shutil.copy(ROOT / "data" / "nda_sample.md", workspace / "msa.md")
    shutil.copy(ROOT / "expected" / "nda.json", workspace / "msa.json")
    (workspace / "reviews" / "good.json").write_text(json.dumps(_oracle("nda")), encoding="utf-8")

    status = run(_env(workspace, case="", contract="msa.md", gold="msa.json"))

    assert status == 0
    summary = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "comparison only, not certifiable" in summary
    assert "| `reviews/good.json` | msa | **PILOT_ELIGIBLE** |" in summary


def test_an_unreadable_review_is_reported_and_the_rest_still_scored(workspace, capsys):
    (workspace / "reviews" / "broken.json").write_text("{", encoding="utf-8")
    (workspace / "reviews" / "good.json").write_text(json.dumps(_oracle("nda")), encoding="utf-8")

    status = run(_env(workspace))

    assert status == 2
    assert "::error file=reviews/broken.json::" in capsys.readouterr().out
    summary = (workspace / "summary.md").read_text(encoding="utf-8")
    assert "Could not score `reviews/broken.json`" in summary
    assert "| `reviews/good.json` | nda | **PILOT_ELIGIBLE** |" in summary


@pytest.mark.parametrize(
    "inputs",
    [
        {"reviews": "nothing/*.json"},
        {"case": ""},
        {"case": "nda", "gold": "g.json"},
        {"case": "", "contract": "c.md"},
        {"aliases": "maybe"},
        {"fail_on": "never"},
    ],
)
def test_bad_inputs_fail_with_status_2(workspace, inputs):
    shutil.copy(STUB, workspace / "reviews" / "vendor.json")

    assert run(_env(workspace, **inputs)) == 2


def test_without_a_step_summary_the_summary_is_printed(workspace, capsys):
    shutil.copy(STUB, workspace / "reviews" / "vendor.json")
    env = _env(workspace)
    del env["GITHUB_STEP_SUMMARY"], env["GITHUB_OUTPUT"]

    run(env)

    assert "## contract-eval" in capsys.readouterr().out


def test_review_files_expand_globs_once_in_order(workspace):
    nested = workspace / "reviews" / "deep"
    nested.mkdir()
    for path in (workspace / "reviews" / "b.json", workspace / "reviews" / "a.json", nested / "a.json"):
        path.write_text("{}", encoding="utf-8")

    found = review_files("reviews/**/*.json reviews/a.json")

    assert found == [Path("reviews/a.json"), Path("reviews/b.json"), Path("reviews/deep/a.json")]


def test_results_for_two_reviews_with_one_name_do_not_collide():
    assert result_stem(Path("vendor-a/nda.json")) != result_stem(Path("vendor-b/nda.json"))
    assert result_stem(Path("../out/r 1.json")) == "out__r__1"


def test_action_yml_passes_every_input_the_step_reads():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    source = (ROOT / "src" / "contract_eval" / "github_action.py").read_text(encoding="utf-8")

    declared = set(re.findall(r"^  ([a-z][a-z-]*):\n    description:", action, flags=re.M))
    passed = dict(re.findall(r"^        (INPUT_[A-Z_]+): \$\{\{ inputs\.([a-z-]+) \}\}", action, flags=re.M))
    read = set(re.findall(r'"(INPUT_[A-Z_]+)"', source))

    assert read == set(passed)
    assert set(passed.values()) | {"python-version"} == declared - {"decision", "results-dir"}
    assert "contract_eval.github_action" in action
