"""Immutable annotation intake, written adjudication and verified reference freeze.

Hashes prove which files were used, not who authored them or whether a legal
judgment is correct. Independence remains a recorded human undertaking.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from contract_eval.adjudication import compare, render_ledger
from contract_eval.annotators import SECOND
from contract_eval.cases import ALL_CASES
from contract_eval.gold_v2 import ExpectedAnswerV2

EVIDENCE = Path("annotations/reference-evidence")
SCHEMA = "contract-review-eval.reference-evidence.v1"


def encoded(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular evidence file: {path.name}")
    data = path.read_bytes()
    if len(data) > 1_000_000:
        raise ValueError(f"Evidence file exceeds 1 MB: {path.name}")
    return data


def load_gold(data: bytes, case: str, source: str) -> ExpectedAnswerV2:
    gold = ExpectedAnswerV2.model_validate_json(data)
    if gold.case != case:
        raise ValueError(f"Wrong case in {case} annotation")
    gold.validate_against_source(source)
    return gold


def _comparison(a: ExpectedAnswerV2, b: ExpectedAnswerV2) -> dict[str, Any]:
    report = asdict(compare(a, b))
    for row in report["disagreements"]:
        row["id"] = digest(encoded(row))
    return report


def _commit_directory(target: Path, files: dict[str, bytes]) -> None:
    """Publish the entire validated bundle or nothing. Never overwrite evidence."""
    if target.is_symlink():
        raise ValueError("An evidence bundle cannot be a symbolic link")
    if target.exists():
        existing = {p.relative_to(target).as_posix(): read_bytes(p) for p in target.rglob("*") if p.is_file()}
        if existing != files:
            raise ValueError(f"{target.name} evidence already exists and differs; refusing overwrite")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".reference-", dir=target.parent))
    try:
        for name, value in files.items():
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(value)
        os.rename(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _intake_files(root: Path, returned: Path, *, imported_names: bool = False) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    records = []
    for case in ALL_CASES:
        source_bytes = read_bytes(root / "data" / f"{case}_sample.md")
        a_bytes = read_bytes(root / "annotations/drafts" / f"{case}.candidate.v2.json")
        b_bytes = read_bytes(returned / (f"{case}.json" if imported_names else f"{case}.{SECOND.slot}.v2.json"))
        source = source_bytes.decode("utf-8")
        a, b = load_gold(a_bytes, case, source), load_gold(b_bytes, case, source)
        if b.review_context.annotator_id not in (SECOND.slot, SECOND.name):
            raise ValueError(f"{case}: return must identify the registered second annotator")
        if b.review_context.annotator_id == a.review_context.annotator_id:
            raise ValueError(f"{case}: two annotation slots cannot identify the same author")
        for field in ("party", "commercial_perspective", "governing_law", "jurisdiction", "objective", "risk_appetite"):
            if getattr(a.review_context, field) != getattr(b.review_context, field):
                raise ValueError(f"{case}: review context differs in {field}; reconcile the task before comparing")
        comparison = _comparison(a, b)
        files[f"returns/{case}.json"] = b_bytes
        files[f"comparisons/{case}.json"] = encoded(comparison)
        files[f"ledgers/{case}.md"] = render_ledger(case, compare(a, b)).encode("utf-8")
        records.append({"case": case, "sourceSha256": digest(source_bytes), "candidateSha256": digest(a_bytes),
                        "returnSha256": digest(b_bytes), "comparisonSha256": digest(encoded(comparison)),
                        "disagreements": len(comparison["disagreements"])})
    files["receipt.json"] = encoded({"schema": SCHEMA, "kind": "independent-returns", "cases": records})
    return files


def import_returns(root: Path, returned: Path) -> dict[str, Any]:
    files = _intake_files(root, returned)
    _commit_directory(root / EVIDENCE / "imported", files)
    return json.loads(files["receipt.json"])


def verify_import(root: Path) -> dict[str, Any]:
    target = root / EVIDENCE / "imported"
    expected = _intake_files(root, target / "returns", imported_names=True)
    actual = {p.relative_to(target).as_posix(): read_bytes(p) for p in target.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Imported references, source inputs or comparison receipt have changed")
    return json.loads(expected["receipt.json"])


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disagreement_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolution: str = Field(min_length=1, max_length=10_000)

    @field_validator("resolution")
    @classmethod
    def substantive(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A written resolution is required")
        return value


class Adjudication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["contract-review-eval.adjudication.v1"] = Field(alias="schema")
    case: str
    comparison_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_gold_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    adjudicator: str = Field(min_length=1)
    decided_at: date
    independence_note: str = Field(min_length=1)
    review_note: str = Field(min_length=1)
    decisions: list[Decision]

    @field_validator("adjudicator", "independence_note", "review_note")
    @classmethod
    def substantive(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Written reviewer evidence is required")
        return value


def adjudication_templates(root: Path, out: Path) -> None:
    receipt = verify_import(root)
    files = {}
    for row in receipt["cases"]:
        case = row["case"]
        comparison = json.loads(read_bytes(root / EVIDENCE / "imported/comparisons" / f"{case}.json"))
        files[f"{case}.adjudication.json"] = encoded({
            "schema": "contract-review-eval.adjudication.v1", "case": case,
            "comparison_sha256": row["comparisonSha256"], "approved_gold_sha256": "",
            "adjudicator": "", "decided_at": "", "independence_note": "", "review_note": "",
            "decisions": [{"disagreement_id": d["id"], "resolution": ""} for d in comparison["disagreements"]],
        })
    _commit_directory(out, files)


def _freeze_files(root: Path, gold_dir: Path, decisions_dir: Path) -> dict[str, bytes]:
    receipt = verify_import(root)
    files: dict[str, bytes] = {}
    records = []
    for row in receipt["cases"]:
        case = row["case"]
        raw = read_bytes(gold_dir / f"{case}.v2.json")
        decision_bytes = read_bytes(decisions_dir / f"{case}.adjudication.json")
        decision = Adjudication.model_validate_json(decision_bytes)
        gold = load_gold(raw, case, read_bytes(root / "data" / f"{case}_sample.md").decode("utf-8"))
        if decision.case != case or decision.comparison_sha256 != row["comparisonSha256"]:
            raise ValueError(f"{case}: adjudication is not bound to the current comparison")
        if decision.approved_gold_sha256 != digest(raw):
            raise ValueError(f"{case}: adjudicator approval does not match the exact proposed gold")
        if (gold.review_context.annotation_status, gold.review_context.adjudication_status) != ("adjudicated", "complete"):
            raise ValueError(f"{case}: proposed gold must be adjudicated and complete")
        if gold.review_context.annotator_id != decision.adjudicator:
            raise ValueError(f"{case}: proposed gold must identify its adjudicator")
        comparison = json.loads(read_bytes(root / EVIDENCE / "imported/comparisons" / f"{case}.json"))
        required = {d["id"] for d in comparison["disagreements"]}
        supplied = [d.disagreement_id for d in decision.decisions]
        if set(supplied) != required or len(supplied) != len(required):
            raise ValueError(f"{case}: every disagreement needs exactly one written decision")
        # The human-approved proposal stays byte-identical in the bundle. Only the
        # annotation status changes in the derived frozen gold, also hash-bound.
        gold.review_context.annotation_status = "frozen"
        files[f"approved/{case}.v2.json"] = raw
        files[f"gold/{case}.v2.json"] = encoded(gold.model_dump(mode="json", by_alias=True))
        files[f"decisions/{case}.adjudication.json"] = decision_bytes
        records.append({**row, "approvedGoldSha256": digest(raw), "goldSha256": digest(files[f"gold/{case}.v2.json"]),
                        "adjudicationSha256": digest(decision_bytes)})
    files["manifest.json"] = encoded({"schema": SCHEMA, "kind": "frozen-references",
                                      "importReceiptSha256": digest(read_bytes(root / EVIDENCE / "imported/receipt.json")), "cases": records})
    return files


def freeze_references(root: Path, gold_dir: Path, decisions_dir: Path) -> None:
    files = _freeze_files(root, gold_dir, decisions_dir)
    _commit_directory(root / EVIDENCE / "frozen", files)


def verify_frozen(root: Path) -> dict[str, Any]:
    target = root / EVIDENCE / "frozen"
    expected = _freeze_files(root, target / "approved", target / "decisions")
    actual = {p.relative_to(target).as_posix(): read_bytes(p) for p in target.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError("Frozen reference evidence has changed")
    return json.loads(expected["manifest.json"])


def reference_status(root: Path) -> dict[str, Any]:
    imported, frozen = root / EVIDENCE / "imported", root / EVIDENCE / "frozen"
    stage, errors, records = "awaiting_returns", [], []
    try:
        # Validate candidates even before an independent return exists.
        for case in ALL_CASES:
            source = read_bytes(root / "data" / f"{case}_sample.md")
            candidate = read_bytes(root / "annotations/drafts" / f"{case}.candidate.v2.json")
            gold = load_gold(candidate, case, source.decode("utf-8"))
            records.append({"case": case, "sourceSha256": digest(source), "candidateSha256": digest(candidate),
                            "obligations": len(gold.obligations)})
        if imported.exists():
            receipt = verify_import(root)
            records = [{**original, **row} for original, row in zip(records, receipt["cases"], strict=True)]
            stage = "awaiting_adjudication"
        if frozen.exists():
            manifest = verify_frozen(root)
            records = [{**original, **row} for original, row in zip(records, manifest["cases"], strict=True)]
            stage = "frozen"
    except (OSError, ValueError, KeyError) as exc:
        stage, errors = "invalid", [str(exc)]
    missing = [] if stage == "frozen" else (["independent_returns", "written_adjudication", "verified_freeze"] if stage == "awaiting_returns" else ["written_adjudication", "verified_freeze"])
    result = {"schema": SCHEMA, "stage": stage, "finalReleaseEligible": stage == "frozen", "cases": records,
              "missing": missing, "errors": errors, "humanReviewRequired": True,
              "limitation": "File integrity and recorded decisions do not establish reviewer independence or legal correctness."}
    return {**result, "integritySha256": digest(encoded(result))}


def load_verified_gold(root: Path, case: str) -> ExpectedAnswerV2:
    if case not in ALL_CASES:
        raise ValueError(f"Unknown case: {case}")
    verify_frozen(root)
    source = read_bytes(root / "data" / f"{case}_sample.md").decode("utf-8")
    return load_gold(read_bytes(root / EVIDENCE / "frozen/gold" / f"{case}.v2.json"), case, source)
