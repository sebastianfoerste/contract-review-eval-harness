"""Synthetic evidence only: these fixtures never become benchmark annotations."""
from pathlib import Path
import json
import shutil

import pytest

from contract_eval.annotators import SECOND
from contract_eval.cases import ALL_CASES
from contract_eval.reference_evidence import (
    EVIDENCE, adjudication_templates, digest, encoded, freeze_references,
    import_returns, load_verified_gold, reference_status, verify_import,
)


@pytest.fixture
def workspace(tmp_path):
    for folder in ("data", "annotations/drafts"):
        shutil.copytree(folder, tmp_path / folder)
    returned = tmp_path / "incoming"
    returned.mkdir()
    for case in ALL_CASES:
        raw = json.loads((tmp_path / "annotations/drafts" / f"{case}.candidate.v2.json").read_text())
        raw["review_context"]["annotator_id"] = SECOND.slot
        first_risk = next(o["risk"] for o in raw["obligations"] if o.get("risk"))
        first_risk["severity"] = "low" if first_risk["severity"] != "low" else "high"
        (returned / f"{case}.{SECOND.slot}.v2.json").write_bytes(encoded(raw))
    return tmp_path


def prepare_decisions(root):
    import_returns(root, root / "incoming")
    adjudication_templates(root, root / "decisions")
    proposed = root / "proposed"
    proposed.mkdir()
    for case in ALL_CASES:
        raw = json.loads((root / "annotations/drafts" / f"{case}.candidate.v2.json").read_text())
        raw["review_context"].update(annotation_status="adjudicated", adjudication_status="complete", annotator_id="Synthetic adjudicator")
        approved = encoded(raw)
        (proposed / f"{case}.v2.json").write_bytes(approved)
        path = root / "decisions" / f"{case}.adjudication.json"
        decision = json.loads(path.read_text())
        decision.update(approved_gold_sha256=digest(approved), adjudicator="Synthetic adjudicator", decided_at="2026-09-15",
                        independence_note="Synthetic fixture only; no real reviewer undertaking.", review_note="Synthetic approval for exercising the evidence chain.")
        for row in decision["decisions"]:
            row["resolution"] = "Synthetic test chooses the first annotation and records that choice."
        path.write_bytes(encoded(decision))


def freeze(root):
    freeze_references(root, root / "proposed", root / "decisions")


def test_candidate_status_cannot_clear_final_release(workspace):
    report = reference_status(workspace)
    assert report["stage"] == "awaiting_returns"
    assert not report["finalReleaseEligible"]
    assert len(report["cases"]) == len(ALL_CASES)


def test_import_is_atomic_and_keeps_original_return_bytes(workspace):
    missing = workspace / "incoming/dpa.annotator-b.v2.json"
    original = missing.read_bytes()
    missing.unlink()
    with pytest.raises(ValueError):
        import_returns(workspace, workspace / "incoming")
    assert not (workspace / EVIDENCE / "imported").exists()
    missing.write_bytes(original)
    import_returns(workspace, workspace / "incoming")
    assert (workspace / EVIDENCE / "imported/returns/dpa.json").read_bytes() == original


def test_repeat_import_is_idempotent_but_replacement_is_rejected(workspace):
    first = import_returns(workspace, workspace / "incoming")
    assert import_returns(workspace, workspace / "incoming") == first
    path = workspace / "incoming/nda.annotator-b.v2.json"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="refusing overwrite"):
        import_returns(workspace, workspace / "incoming")
    assert verify_import(workspace) == first


@pytest.mark.parametrize("field,value", [("annotator_id", "annotator-a"), ("party", "Different client")])
def test_return_identity_and_review_context_are_validated(workspace, field, value):
    path = workspace / "incoming/nda.annotator-b.v2.json"
    raw = json.loads(path.read_text())
    raw["review_context"][field] = value
    path.write_bytes(encoded(raw))
    with pytest.raises(ValueError):
        import_returns(workspace, workspace / "incoming")


def test_edited_source_or_return_invalidates_the_import(workspace):
    import_returns(workspace, workspace / "incoming")
    path = workspace / EVIDENCE / "imported/returns/nda.json"
    path.write_bytes(path.read_bytes() + b"\n")
    assert reference_status(workspace)["stage"] == "invalid"


def test_templates_are_not_adjudication(workspace):
    import_returns(workspace, workspace / "incoming")
    adjudication_templates(workspace, workspace / "decisions")
    assert reference_status(workspace)["stage"] == "awaiting_adjudication"
    raw = json.loads((workspace / "decisions/nda.adjudication.json").read_text())
    assert raw["decisions"] and raw["adjudicator"] == ""


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "blank", "wrong_hash", "wrong_case", "wrong_gold", "unreviewed"])
def test_incomplete_or_unbound_adjudication_cannot_freeze(workspace, mutation):
    prepare_decisions(workspace)
    path = workspace / "decisions/nda.adjudication.json"
    raw = json.loads(path.read_text())
    if mutation == "missing": raw["decisions"] = []
    elif mutation == "duplicate": raw["decisions"].append(raw["decisions"][0])
    elif mutation == "blank": raw["decisions"][0]["resolution"] = " "
    elif mutation == "wrong_hash": raw["comparison_sha256"] = "0" * 64
    elif mutation == "wrong_case": raw["case"] = "saas"
    elif mutation == "wrong_gold": raw["approved_gold_sha256"] = "0" * 64
    elif mutation == "unreviewed":
        proposed = workspace / "proposed/nda.v2.json"
        gold = json.loads(proposed.read_text())
        gold["review_context"]["annotation_status"] = "candidate"
        proposed.write_bytes(encoded(gold))
        raw["approved_gold_sha256"] = digest(proposed.read_bytes())
    path.write_bytes(encoded(raw))
    with pytest.raises(ValueError): freeze(workspace)
    assert not (workspace / EVIDENCE / "frozen").exists()


def test_complete_written_evidence_freezes_and_survives_repeat_run(workspace):
    prepare_decisions(workspace)
    freeze(workspace)
    freeze(workspace)
    report = reference_status(workspace)
    assert report["finalReleaseEligible"] and report["stage"] == "frozen"
    assert report["missing"] == []
    assert load_verified_gold(workspace, "dpa").review_context.annotation_status == "frozen"
    approved = workspace / "proposed/dpa.v2.json"
    assert (workspace / EVIDENCE / "frozen/approved/dpa.v2.json").read_bytes() == approved.read_bytes()


@pytest.mark.parametrize("file", ["data/nda_sample.md", "annotations/drafts/nda.candidate.v2.json", "annotations/reference-evidence/frozen/gold/nda.v2.json", "annotations/reference-evidence/frozen/decisions/nda.adjudication.json"])
def test_post_freeze_drift_revokes_eligibility(workspace, file):
    prepare_decisions(workspace)
    freeze(workspace)
    path = workspace / file
    path.write_bytes(path.read_bytes() + b"\n")
    assert not reference_status(workspace)["finalReleaseEligible"]
    assert reference_status(workspace)["stage"] == "invalid"


def test_setting_status_flags_alone_is_not_evidence(workspace):
    for case in ALL_CASES:
        path = workspace / "annotations/drafts" / f"{case}.candidate.v2.json"
        raw = json.loads(path.read_text())
        raw["review_context"].update(annotation_status="frozen", adjudication_status="complete")
        path.write_bytes(encoded(raw))
    assert not reference_status(workspace)["finalReleaseEligible"]
