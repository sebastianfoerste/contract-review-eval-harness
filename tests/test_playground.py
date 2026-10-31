"""The browser playground scores through the CLI's own path and labels findings truthfully."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from contract_eval.cases import ALL_CASES
from contract_eval.cli import score
from contract_eval.scorer import normalize_text

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bridge = _load("playground_score", ROOT / "playground" / "score.py")
site = _load("build_site", ROOT / "scripts" / "build_site.py")
SAMPLES = site.playground_samples()


@pytest.fixture(autouse=True)
def _workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "WORKDIR", tmp_path / "bridge")


def _score(review: dict, case: str, aliases: str = "on", name: str = "") -> dict:
    return json.loads(bridge.score_text(json.dumps(review, indent=2), case, aliases, name))


@pytest.mark.parametrize("case", ALL_CASES)
@pytest.mark.parametrize("aliases", ["on", "off"])
def test_bridge_result_is_the_cli_result_for_the_same_file(case, aliases, tmp_path, monkeypatch):
    text = json.dumps(SAMPLES["cases"][case]["reviews"]["stub"], indent=2)
    folder = tmp_path / "cli"
    folder.mkdir()
    (folder / "my-review.json").write_text(text, encoding="utf-8")
    monkeypatch.chdir(folder)
    expected = score(Path("my-review.json"), case=case, alias_mode=aliases)
    monkeypatch.chdir(ROOT)

    payload = json.loads(bridge.score_text(text, case, aliases, "C:\\exports\\my-review.json"))

    assert payload["result"] == expected
    assert payload["result_json"] == json.dumps(expected, indent=2, ensure_ascii=False) + "\n"
    assert payload["result"]["inputs"]["review_output"]["path"] == "my-review.json"


@pytest.mark.parametrize("case", ALL_CASES)
def test_each_example_reaches_its_decision(case):
    reviews = SAMPLES["cases"][case]["reviews"]
    decisions = {name: _score(review, case)["result"]["decision"] for name, review in reviews.items()}
    assert decisions == {
        "stub": "REJECT",
        "grounded": "HUMAN_REVIEW_REQUIRED",
        "answer_key": "PILOT_ELIGIBLE",
    }


@pytest.mark.parametrize("case", ALL_CASES)
@pytest.mark.parametrize("example", ["stub", "grounded", "answer_key"])
def test_findings_agree_with_the_decision(case, example):
    payload = _score(SAMPLES["cases"][case]["reviews"][example], case)
    result, rows = payload["result"], payload["findings"]
    blockers = [row for row in rows if row["status"] == "blocker"]
    review_keys = {row["key"] for row in rows if row["status"] == "review"}

    # One blocker row per ungrounded citation and one per grounded quote under the floor.
    assert len(blockers) == result["scores"]["hallucination_count"] + result["scores"]["citation_short_count"]
    assert bool(blockers) == bool(result["blockers"])
    assert review_keys == set(result["review_items"])
    assert review_keys <= set(payload["requirements"])


def test_a_short_quote_is_a_blocker_finding_and_an_unquoted_flag_a_review_finding():
    review = json.loads(json.dumps(SAMPLES["cases"]["nda"]["reviews"]["answer_key"]))
    # Every flag keeps its anchor quote except the first, which is cut to one word.
    flagged = review["risk_flags"][0]["clause_type"]
    for citation in review["citations"]:
        if citation["clause_type"] == flagged:
            citation["quote"] = citation["quote"].split()[0]
    payload = _score(review, "nda")
    result, rows = payload["result"], payload["findings"]

    assert result["decision"] == "REJECT"
    assert result["blockers"] == ["degenerate_citation_detected"]
    assert "risk_flag_without_evidence" in result["review_items"]
    short = [row for row in rows if row["key"] == "degenerate_citation_detected"]
    assert [row["status"] for row in short] == ["blocker"]
    assert short[0]["span"] is not None
    unquoted = [row for row in rows if row["key"] == "risk_flag_without_evidence"]
    assert [row["label"] for row in unquoted] == [flagged]
    assert payload["note"].startswith("Every citation is an exact span of the contract, but")


@pytest.mark.parametrize("case", ALL_CASES)
def test_highlighted_spans_are_the_quoted_text(case):
    payload = _score(SAMPLES["cases"][case]["reviews"]["stub"], case)
    contract = SAMPLES["cases"][case]["contract"]
    grounded = [row for row in payload["findings"] if row["key"] == "citation_grounded"]
    assert grounded
    for row in grounded:
        start, end = row["span"]
        assert normalize_text(contract[start:end]) == normalize_text(row["label"].strip("“”"))


def test_a_review_without_citations_is_named_as_such():
    review = {"clauses": [], "risk_flags": [], "citations": []}
    payload = _score(review, "nda")
    assert payload["result"]["decision"] == "REJECT"
    assert [row["label"] for row in payload["findings"] if row["status"] == "blocker"] == ["The review cites nothing"]


def test_invalid_review_returns_the_cli_message_and_no_traceback():
    payload = json.loads(bridge.score_text('{"clauses": []}', "nda", "on", ""))
    assert set(payload) == {"error"}
    assert payload["error"].startswith("review.json is not a plain review JSON")
    assert "Traceback" not in payload["error"]


def test_site_build_with_a_wheel_adds_the_playground(tmp_path):
    wheel = tmp_path / "contract_eval-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    written = site.build(tmp_path / "site", wheel=wheel)
    playground = tmp_path / "site" / "playground"

    page = (playground / "index.html").read_text(encoding="utf-8")
    assert site.WHEEL_MARKER not in page
    assert f'data-wheel="{wheel.name}"' in page
    assert (playground / wheel.name).read_bytes() == b"wheel"
    for name in (*site.PLAYGROUND_FILES, "samples.json"):
        assert playground / name in written
    assert 'href="playground/"' in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")


def test_site_build_without_a_wheel_leaves_the_playground_out(tmp_path):
    site.build(tmp_path)
    assert not (tmp_path / "playground").exists()
    assert "playground/" not in (tmp_path / "index.html").read_text(encoding="utf-8")
