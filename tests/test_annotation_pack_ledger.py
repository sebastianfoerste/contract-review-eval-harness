"""The generator's primary-law ledger is the sent pack's ledger plus its recorded corrections.

The pack sent to Annotator B on 2026-09-06 is frozen: `annotations/pack/MANIFEST.json`
records every file's hash and `test_annotation_pack.py` fails if a byte of it changes.
The copy of the ledger inside `scripts/build_annotation_pack.py` is the corrected text,
so the two copies differ on purpose. Nothing used to pin that difference: an edit to
the generator was invisible, and a correction owed to the annotator had no record.

`LEDGER_CORRECTIONS` in the generator is that record. This test applies the recorded
replacements to the frozen file and requires the result to equal what the generator
writes today. A correction made in the generator without being recorded fails here, a
recorded correction the generator does not carry fails here, and an erratum to the
annotator can be checked against the same list.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "annotations" / "pack"
SENT_LEDGER = PACK / "primary-law-ledger.md"


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_annotation_pack", ROOT / "scripts" / "build_annotation_pack.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sent_ledger() -> str:
    return SENT_LEDGER.read_text(encoding="utf-8")


def _corrected_ledger(generator: ModuleType) -> str:
    text = _sent_ledger()
    for sent, corrected in generator.LEDGER_CORRECTIONS:
        text = text.replace(sent, corrected)
    return text


def test_the_sent_ledger_is_the_file_the_manifest_froze() -> None:
    """The baseline of every correction is the file as sent, not a later edit of it."""
    manifest = json.loads((PACK / "MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["pack_id"] == "blind-annotation-2026-09-02"
    recorded = manifest["files"]["primary-law-ledger.md"]
    assert hashlib.sha256(SENT_LEDGER.read_bytes()).hexdigest() == recorded


def test_every_recorded_correction_applies_exactly_once() -> None:
    generator = _generator()
    sent_text = _sent_ledger()
    assert generator.LEDGER_CORRECTIONS, "the generator records no corrections"
    for sent, corrected in generator.LEDGER_CORRECTIONS:
        assert sent != corrected, sent
        assert sent_text.count(sent) == 1, f"not exactly once in the sent ledger: {sent!r}"
        assert corrected not in sent_text, f"already in the sent ledger: {corrected!r}"


def test_the_generator_writes_the_sent_ledger_plus_the_corrections() -> None:
    generator = _generator()
    generated = generator._primary_law_ledger()
    corrected = _corrected_ledger(generator)
    assert generated == corrected, (
        "scripts/build_annotation_pack.py's ledger differs from the sent pack's ledger plus "
        "LEDGER_CORRECTIONS; record the change there and in an erratum, never in the sent file"
    )
    assert generated != _sent_ledger(), "the corrections changed nothing"


def test_the_corrections_cover_the_points_found_on_2026_10_31() -> None:
    """A later rewrite of the list must not quietly drop a correction already owed."""
    generated = _generator()._primary_law_ledger()
    sent_text = _sent_ledger()
    for fragment in ("Art. 34", "Art. 36", "Art. 44 to 50", "EDPB Opinion 22/2024"):
        assert fragment in generated, f"the corrected ledger lost {fragment!r}"
        assert fragment not in sent_text, f"{fragment!r} was already in the sent ledger"
    assert "Art. 44 to 49" not in generated
