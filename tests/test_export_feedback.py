"""The feedback exporter writes into another repository's data file.

The dashboard validates `data/feedback.json` at load and in its private-boundary gate: an
item without an `origin`, or with an origin that is not exactly
`{"kind": "synthetic_fixture"}`, takes the dashboard down. Nothing in this repository
fails when that happens, so these tests pin the item shape on the side that produces it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from contract_eval.cli import evaluate

ROOT = Path(__file__).resolve().parents[1]

SYNTHETIC_ORIGIN = {"kind": "synthetic_fixture"}

# Key order of `feedbackItemSchema` in the dashboard's lib/schema.ts.
DASHBOARD_FEEDBACK_KEYS = [
    "id",
    "origin",
    "accountId",
    "sourcePersona",
    "text",
    "theme",
    "productArea",
    "severity",
    "status",
]

EXISTING_ITEM = {
    "id": "fb-001",
    "origin": {"kind": "synthetic_fixture"},
    "accountId": "acct-001",
    "sourcePersona": "Associate",
    "text": "Clause extraction misses cross-referenced definitions in long SPAs.",
    "theme": "Citation and context handling",
    "productArea": "review",
    "severity": "high",
    "status": "shared_with_product",
}


def _exporter():
    spec = importlib.util.spec_from_file_location(
        "export_feedback", ROOT / "scripts" / "export_feedback.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Run the exporter against a failing run and return the dashboard file it wrote."""
    history = tmp_path / "history"
    history.mkdir()
    run = {
        "scores": {
            "nda": {"hallucination_count": 1, "citation_grounding": 0.8},
            "saas": {"hallucination_count": 0, "citation_grounding": 0.85},
            "clean": {"hallucination_count": 0, "citation_grounding": 1.0},
        }
    }
    (history / "run_20260101_000000.json").write_text(json.dumps(run), encoding="utf-8")

    dashboard = tmp_path / "dashboard"
    (dashboard / "data").mkdir(parents=True)
    feedback_file = dashboard / "data" / "feedback.json"
    feedback_file.write_text(json.dumps([EXISTING_ITEM]), encoding="utf-8")

    # Without --history the exporter reads `history/` relative to the working directory.
    monkeypatch.chdir(tmp_path)
    _exporter().export_feedback(write=True, dashboard_path=str(dashboard))
    return json.loads(feedback_file.read_text(encoding="utf-8"))


def _generated(exported: list[dict]) -> list[dict]:
    return [item for item in exported if item["id"].startswith("fb-gen-")]


def test_every_generated_item_states_a_synthetic_fixture_origin(exported: list[dict]) -> None:
    generated = _generated(exported)
    assert len(generated) == 2
    # Whole-object equality: the dashboard's origin schema is strict, so an extra key
    # inside `origin` fails the load as surely as a wrong kind.
    assert all(item["origin"] == SYNTHETIC_ORIGIN for item in generated)


def test_generated_items_carry_the_dashboard_keys_with_origin_after_id(
    exported: list[dict],
) -> None:
    assert all(list(item) == DASHBOARD_FEEDBACK_KEYS for item in _generated(exported))


def test_the_dropped_field_name_is_not_written(exported: list[dict]) -> None:
    # The dashboard strips unknown top-level keys without complaint, so a leftover
    # `evidenceClass` would never surface there.
    assert all("evidenceClass" not in item for item in exported)
    source = (ROOT / "scripts" / "export_feedback.py").read_text(encoding="utf-8")
    assert "evidenceClass" not in source


def test_the_exporter_cannot_be_pointed_at_a_real_evidence_kind() -> None:
    assert _exporter().ORIGIN_KIND == "synthetic_fixture"


def test_existing_dashboard_items_are_left_untouched(exported: list[dict]) -> None:
    assert exported[0] == EXISTING_ITEM


def test_the_history_option_reads_a_run_written_under_another_out_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # evaluate writes history/ under its --out directory, so ./history holds only the
    # runs made with the default --out.
    evaluate(case="nda", live=False, out_dir=tmp_path / "out")
    dashboard = tmp_path / "dashboard"
    (dashboard / "data").mkdir(parents=True)
    feedback_file = dashboard / "data" / "feedback.json"
    feedback_file.write_text("[]", encoding="utf-8")

    # The working directory has no history/, so only --history can find the run.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "export_feedback.py", "--write", "--dashboard", str(dashboard),
        "--history", str(tmp_path / "out" / "history"),
    ])
    _exporter().main()

    (item,) = json.loads(feedback_file.read_text(encoding="utf-8"))
    assert item["origin"] == SYNTHETIC_ORIGIN
    assert "NDA review" in item["text"]
