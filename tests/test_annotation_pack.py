"""The pack's blindness must be verifiable, not asserted."""

import json
from pathlib import Path

PACK = Path("annotations/pack")


def _pack_text() -> str:
    """Everything the annotator can read, minus the manifest's exclusion record.

    The manifest names what was withheld, which is the audit trail rather than a leak.
    Scanning it would make the record of an exclusion look like the exclusion failing.
    """
    parts = []
    for path in sorted(PACK.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "MANIFEST.json":
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.pop("excluded_from_pack", None)
            parts.append(json.dumps(manifest))
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_pack_contains_no_gold_severities_or_rationales():
    """Annotator B must not see Annotator A's calibration."""
    blob = _pack_text()

    for case in ("nda", "saas", "dpa"):
        gold = json.loads(Path(f"expected/{case}.json").read_text())
        for rationale in gold["severity_rationale"].values():
            # A distinctive fragment is enough; whole-string absence proves the point.
            assert rationale[:60] not in blob, f"{case}: a gold rationale leaked into the pack"
        for alias in gold["clause_aliases"]:
            assert f'"{alias}"' not in blob, f"{case}: alias {alias} leaked into the pack"


def test_pack_templates_carry_no_obligations():
    for path in sorted((PACK / "templates").glob("*.json")):
        template = json.loads(path.read_text())
        assert template["obligations"] == [], f"{path.name} must start empty"
        assert template["review_context"]["annotator_id"] == "annotator-b"


def test_pack_contains_no_model_output_or_scores():
    blob = _pack_text()

    for marker in ("clause_f1", "risk_precision", "hallucination_count",
                   "PILOT_ELIGIBLE", "release-certificate", "span_coverage"):
        assert marker not in blob, f"pack leaks {marker}"


def test_pack_manifest_lists_every_file_with_a_matching_hash():
    import hashlib

    manifest = json.loads((PACK / "MANIFEST.json").read_text())
    for rel, recorded in manifest["files"].items():
        actual = hashlib.sha256((PACK / rel).read_bytes()).hexdigest()
        assert actual == recorded, f"{rel}: hash drift"

    on_disk = {
        str(p.relative_to(PACK)) for p in PACK.rglob("*")
        if p.is_file() and p.name != "MANIFEST.json"
    }
    assert on_disk == set(manifest["files"]), "manifest and pack contents disagree"


def test_pack_records_what_it_withholds():
    manifest = json.loads((PACK / "MANIFEST.json").read_text())
    excluded = " ".join(manifest["excluded_from_pack"]).lower()

    for expected in ("expected/", "candidate", "alias", "severity", "model output"):
        assert expected in excluded


def test_pack_ships_the_contracts_verbatim():
    """Offsets returned by Annotator B must index the same bytes."""
    for case in ("nda", "saas", "dpa"):
        assert (PACK / "contracts" / f"{case}_sample.md").read_text() == (
            Path(f"data/{case}_sample.md").read_text()
        )
