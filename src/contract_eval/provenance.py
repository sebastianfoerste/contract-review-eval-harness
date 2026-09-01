"""Provenance for a scored run.

A score is only reproducible if three things travel with it: which adapter output
was scored, which gold sets it was scored against, and which scorer produced the
numbers. Conflating them hides re-scoring: the 2026-08-28 adapter output was
re-scored on 2026-08-31 under a changed scorer, and only separate fields make that
visible.
"""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scorer_version() -> str:
    try:
        return metadata.version("contract-eval")
    except metadata.PackageNotFoundError:  # editable checkout without install
        return "unknown"


def gold_set_digests(cases: tuple[str, ...], root: Path = Path(".")) -> dict[str, str]:
    return {case: _sha256(root / "expected" / f"{case}.json") for case in cases}


def source_digests(cases: tuple[str, ...], root: Path = Path(".")) -> dict[str, str]:
    return {case: _sha256(root / "data" / f"{case}_sample.md") for case in cases}


def run_provenance(
    cases: tuple[str, ...],
    *,
    adapter: str,
    output_generated_at: str | None = None,
    scored_at: str | None = None,
    root: Path = Path("."),
) -> dict[str, object]:
    """Describe a scored run.

    `output_generated_at` is when the adapter produced the reviewed output.
    `scored_at` is when the scorer ran over it. They differ whenever an output is
    re-scored, and a run that does not know its own output date says so with null
    rather than borrowing the scoring date.
    """
    return {
        "schema": "contract-review-eval.run-provenance.v1",
        "adapter": adapter,
        "output_generated_at": output_generated_at,
        "scored_at": scored_at,
        "scorer_version": scorer_version(),
        "gold_set_sha256": gold_set_digests(cases, root),
        "source_contract_sha256": source_digests(cases, root),
    }


def write_provenance(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
