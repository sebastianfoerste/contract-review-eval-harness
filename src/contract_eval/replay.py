"""Re-score a captured review offline, through the production scorer.

Replay never contacts a provider. It verifies that the capture is intact, that the
inputs it embeds are the ones it claims, and then hands the parsed output to the same
`score_review` a live evaluation uses.

    capture -> schema -> integrity -> embedded inputs -> current-input drift -> score
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contract_eval.capture import (
    CAPTURE_SCHEMA,
    CapturedReview,
    canonical_sha256,
    read_capture,
    text_sha256,
)
from contract_eval.cli import score_review
from contract_eval.models import ExpectedAnswer

REPLAY_RESULT_SCHEMA = "contract-review-eval.replay-result.v1"
PROVENANCE_SCHEMA = "contract-review-eval.run-provenance.v2"


class ReplayError(RuntimeError):
    """The capture cannot be trusted or cannot be scored."""


def verify_capture(capture: CapturedReview, *, root: Path = Path(".")) -> dict[str, Any]:
    """Check a capture's authenticity and report current-input drift.

    Authenticity and drift are separate questions. A capture can be perfectly
    authentic while the working tree has moved on; conflating the two would either
    hide tampering or reject legitimate history.
    """
    errors: list[str] = []
    if capture.schema_version != CAPTURE_SCHEMA:
        errors.append(f"capture_schema_unsupported:{capture.schema_version!r}")
    if not capture.integrity_ok():
        errors.append("capture_integrity_mismatch")

    if capture.source.sha256 != text_sha256(capture.source.text):
        errors.append("embedded_source_hash_mismatch")
    if capture.gold and capture.gold.sha256 != text_sha256(capture.gold.text):
        errors.append("embedded_gold_hash_mismatch")
    if capture.response.raw_text is not None:
        if capture.response.raw_text_sha256 != text_sha256(capture.response.raw_text):
            errors.append("raw_response_hash_mismatch")
    if capture.output is not None:
        if capture.output_sha256 != text_sha256(capture.output.model_dump_json()):
            errors.append("parsed_output_hash_mismatch")

    drift: list[str] = []
    current_source = root / capture.source.path
    if current_source.is_file():
        if text_sha256(current_source.read_text(encoding="utf-8")) != capture.source.sha256:
            drift.append(f"source:{capture.source.path}")
    else:
        drift.append(f"source_missing:{capture.source.path}")
    if capture.gold:
        current_gold = root / capture.gold.path
        if current_gold.is_file():
            if text_sha256(current_gold.read_text(encoding="utf-8")) != capture.gold.sha256:
                drift.append(f"gold:{capture.gold.path}")
        else:
            drift.append(f"gold_missing:{capture.gold.path}")

    return {
        "authentic": not errors,
        "errors": errors,
        "state": capture.state,
        "scoreable": capture.is_scoreable(),
        "input_drift": drift,
    }


def replay(
    capture: CapturedReview,
    *,
    alias_modes: tuple[str, ...] = ("on",),
    allow_input_drift: bool = False,
    root: Path = Path("."),
) -> dict[str, Any]:
    """Score a capture under one or more alias modes."""
    verification = verify_capture(capture, root=root)
    if not verification["authentic"]:
        raise ReplayError(
            "capture failed verification: " + ", ".join(verification["errors"])
        )
    if not verification["scoreable"]:
        raise ReplayError(
            f"capture state {capture.state!r} carries no scoreable output; "
            "it is an authentic record of an attempt, not a result"
        )

    drift = verification["input_drift"]
    if drift and not allow_input_drift:
        raise ReplayError(
            "current inputs differ from the capture: " + ", ".join(drift) +
            "; pass --allow-input-drift to reproduce the historical result, which is "
            "then comparison-only and ineligible for certification"
        )

    # Score against the embedded snapshots, never the working tree. That is what makes
    # the result a reproduction of the original rather than a fresh evaluation.
    expected = ExpectedAnswer.model_validate(json.loads(capture.gold.text))
    scores = {
        mode: score_review(capture.source.text, expected, capture.output, alias_mode=mode)
        for mode in alias_modes
    }

    comparison_only = bool(drift)
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "capture_id": capture.capture_id,
        "capture_sha256": capture.integrity_sha256,
        "parsed_output_sha256": capture.output_sha256,
        "source_sha256": capture.source.sha256,
        "gold_sha256": capture.gold.sha256,
        "prompt_sha256": capture.request.prompt_sha256 if capture.request else None,
        "requested_model": capture.request.model if capture.request else None,
        "effort": capture.request.effort if capture.request else None,
        "returned_model": capture.response.returned_model,
        "adapter_id": capture.adapter_id,
        "parser_version": capture.parser_version,
        "prompt_version": capture.prompt_version,
        "repository_commit": capture.repository_commit,
        "output_generated_at": capture.completed_at,
        "alias_modes": list(alias_modes),
        "input_drift": drift,
        "comparison_only": comparison_only,
    }

    payload = {
        "schema": REPLAY_RESULT_SCHEMA,
        "case": capture.case,
        "capture_id": capture.capture_id,
        "eligible_for_certification": not comparison_only,
        "provenance": provenance,
        "scores": scores,
    }
    return {**payload, "result_sha256": canonical_sha256(payload)}


def load(path: Path) -> CapturedReview:
    return read_capture(path)
