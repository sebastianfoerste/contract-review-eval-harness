"""The leaderboard is derived from committed outputs by the production scorer, not typed."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from contract_eval import ReviewOutput, load_case, score_review
from contract_eval.capture import read_capture
from contract_eval.cases import ALL_CASES

ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location("build_leaderboard", ROOT / "scripts" / "build_leaderboard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


leaderboard = _load_script()


@pytest.fixture(scope="module")
def payload():
    return leaderboard.build(ROOT)


def _row(payload, tool):
    matches = [row for row in payload["rows"] if row["tool"] == tool]
    assert len(matches) == 1, f"expected one row for {tool!r}"
    return matches[0]


def test_captured_row_reproduces_score_review(payload):
    capture = read_capture(ROOT / "examples" / "captures" / "legacy-nda-2026-09-01.json")
    case = load_case("nda", root=ROOT)
    expected = score_review(case.source_text, case.expected, capture.output, alias_mode="on")

    row = _row(payload, "claude-opus-5")
    nda = next(item for item in row["per_case"] if item["case"] == "nda")
    for name, value in nda["scores"].items():
        assert value == expected[name], name
    # The capture is the manifest's raw output imported, so it joins that row rather
    # than counting the same generation twice.
    assert nda["origin"]["capture_ids"] == ["legacy-nda-2026-09-01"]
    assert row["date"] == "2026-09-01"
    assert row["metrics"]["clause_f1"] == pytest.approx(
        sum(item["scores"]["clause_f1"] for item in row["per_case"]) / len(row["per_case"])
    )


def test_stub_baseline_row_is_present_and_rescored(payload):
    row = _row(payload, leaderboard.STUB_LABEL)
    assert row["kind"] == "baseline"
    assert row["cases"] == sorted(ALL_CASES)
    case = load_case("saas", root=ROOT)
    review = ReviewOutput.model_validate_json((ROOT / "fixtures" / "saas_stub.json").read_bytes())
    expected = score_review(case.source_text, case.expected, review, alias_mode="on")
    saas = next(item for item in row["per_case"] if item["case"] == "saas")
    assert saas["scores"]["citation_grounding"] == expected["citation_grounding"]
    # The stub carries a fabricated citation on purpose, so it can never be eligible.
    assert row["metrics"]["hallucination_count"] > 0
    assert row["verdict"] == "REJECT"


def test_verdict_is_the_worst_case_decision(payload):
    for row in payload["rows"]:
        decisions = [item["decision"] for item in row["per_case"]]
        worst = next(str(v) for v in leaderboard.VERDICT_ORDER if str(v) in decisions)
        assert row["verdict"] == worst


def test_unrecorded_cost_and_latency_are_null_not_zero(payload):
    for row in payload["rows"]:
        assert row["cost_usd"] is None
        assert row["latency_ms"] is None
    markdown = leaderboard.render_markdown(payload)
    assert "| n/a | n/a |" in markdown


def test_ordering_and_bytes_are_deterministic(payload):
    again = leaderboard.build(ROOT)
    assert leaderboard.render_json(again) == leaderboard.render_json(payload)
    assert leaderboard.render_markdown(again) == leaderboard.render_markdown(payload)
    assert payload["rows"] == sorted(payload["rows"], key=leaderboard._sort_key)
    assert [row["tool"] for row in payload["rows"]] == ["claude-opus-5", leaderboard.STUB_LABEL]


def _copy_committed(tmp_path: Path) -> Path:
    for rel in leaderboard.OUTPUTS:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


def test_check_passes_on_the_committed_files(tmp_path, capsys):
    out = _copy_committed(tmp_path)
    assert leaderboard.main(["--check", "--out", str(out)]) == 0
    assert "check passed" in capsys.readouterr().out


def test_check_fails_after_tampering(tmp_path, capsys):
    out = _copy_committed(tmp_path)
    tampered = out / leaderboard.OUTPUT_JSON
    data = json.loads(tampered.read_text(encoding="utf-8"))
    data["rows"][0]["metrics"]["clause_f1"] = 1.0
    tampered.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert leaderboard.main(["--check", "--out", str(out)]) == 1
    assert f"{leaderboard.OUTPUT_JSON}: differs" in capsys.readouterr().out


def test_check_fails_when_a_file_is_missing(tmp_path):
    out = _copy_committed(tmp_path)
    (out / leaderboard.OUTPUT_MARKDOWN).unlink()
    assert leaderboard.check(out) == [f"{leaderboard.OUTPUT_MARKDOWN}: missing"]


def test_a_raw_output_that_no_longer_matches_its_manifest_is_refused(tmp_path):
    root = tmp_path / "repo"
    for name in ("data", "expected", "fixtures", "examples/raw-output", "examples/captures"):
        shutil.copytree(ROOT / name, root / name)
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    raw = root / "examples" / "raw-output" / "nda-claude-opus-5-2026-09-01.json"
    raw.write_bytes(raw.read_bytes().replace(b"perpetuity", b"perpetuity!", 1))

    with pytest.raises(leaderboard.LeaderboardError, match="MANIFEST"):
        leaderboard.build(root)
