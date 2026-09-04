"""The helper the annotator actually runs.

It ships inside the pack, so it is the one piece of this repository that executes on
someone else's machine with no repository around it. If it returns a plausible but
wrong span, the annotation parses, scores, and disagrees with the first annotator for a
reason nobody can see. These tests pin the three answers it is allowed to give.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "annotations" / "pack" / "contracts" / "nda_sample.md"


def _helper():
    spec = importlib.util.spec_from_file_location(
        "pack_offsets_helper", ROOT / "scripts" / "pack_offsets_helper.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def source() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def test_a_unique_quote_round_trips(source: str) -> None:
    start, end = _helper().find(source, "Confidential Information means")
    assert source[start:end] == "Confidential Information means"


def test_a_quote_broken_by_a_line_break_still_resolves_to_raw_offsets(source: str) -> None:
    """Copying out of a rendered view reflows the text; the offsets must not.

    The annotator quotes from a reader, not from the bytes. The span still has to
    address the file as delivered, or it will not resolve on this side.
    """
    index = source.index("\n", 600)
    raw = source[index - 30 : index + 30]
    assert "\n" in raw, "this fixture must span a line break to be worth anything"

    flattened = " ".join(raw.split())
    start, end = _helper().find(source, flattened)

    assert source[start:end] == raw
    assert "\n" in source[start:end]


def test_an_ambiguous_quote_is_refused_rather_than_resolved_to_the_first_hit(
    source: str,
) -> None:
    assert source.count("Confidential Information") > 1
    with pytest.raises(ValueError, match="appears"):
        _helper().find(source, "Confidential Information")


def test_an_absent_quote_is_refused(source: str) -> None:
    with pytest.raises(ValueError, match="not found"):
        _helper().find(source, "no such words appear in this agreement")


def test_the_shipped_copy_matches_the_source_of_truth() -> None:
    """The pack carries a copy. A stale copy is a silently different tool."""
    shipped = ROOT / "annotations" / "pack" / "offsets.py"
    assert shipped.read_text(encoding="utf-8") == (
        ROOT / "scripts" / "pack_offsets_helper.py"
    ).read_text(encoding="utf-8")
