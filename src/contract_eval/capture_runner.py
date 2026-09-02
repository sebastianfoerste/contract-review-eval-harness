"""Drive one adapter attempt through its states, persisting evidence at each step."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from contract_eval.capture import (
    CaptureError,
    CapturedReview,
    ProviderRequest,
    ProviderResponse,
    snapshot_of,
    text_sha256,
    utc_now,
    write_capture,
)
from contract_eval.models import ReviewOutput

PROMPT_VERSION = "contract-review.prompt.v2"
PARSER_VERSION = "contract-review.parser.v1"


class CaptureFailure(RuntimeError):
    """An attempt ended without a scoreable output. The capture holds the evidence."""

    def __init__(self, message: str, capture: CapturedReview, path: Path) -> None:
        super().__init__(message)
        self.capture = capture
        self.path = path


def repository_commit(root: Path = Path(".")) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def new_run_id() -> str:
    return f"run-{utc_now().replace(':', '').replace('.', '')}-{uuid.uuid4().hex[:8]}"


def capture_attempt(
    adapter,
    *,
    case: str,
    run_id: str,
    out_dir: Path,
    origin: str,
    adapter_id: str,
    root: Path = Path("."),
    scenario_id: str | None = None,
    variant: str = "original",
    run_index: int = 0,
    source_text: str | None = None,
) -> CapturedReview:
    """Run one attempt, writing the capture before and after the provider call.

    The initial write happens before any external request. If it fails, the request
    is never made: a provider call whose result cannot be recorded produces an
    unauditable score, which is the situation captures exist to prevent.
    """
    capture_id = f"{case}-{run_index}-{uuid.uuid4().hex[:8]}"
    path = out_dir / f"{capture_id}.json"

    source_path = Path("data") / f"{case}_sample.md"
    gold_path = Path("expected") / f"{case}.json"

    capture = CapturedReview(
        capture_id=capture_id,
        run_id=run_id,
        origin=origin,  # type: ignore[arg-type]
        state="started",
        case=case,
        scenario_id=scenario_id,
        variant=variant,  # type: ignore[arg-type]
        run_index=run_index,
        started_at=utc_now(),
        adapter_id=adapter_id,
        prompt_version=PROMPT_VERSION,
        parser_version=PARSER_VERSION,
        repository_commit=repository_commit(root),
        source=snapshot_of(source_path, root=root),
        gold=snapshot_of(gold_path, root=root) if (root / gold_path).is_file() else None,
    )
    if source_text is not None:
        # A mutated campaign variant is not the file on disk; record what was sent.
        capture = capture.model_copy(
            update={
                "source": capture.source.model_copy(
                    update={"text": source_text, "sha256": text_sha256(source_text)}
                )
            }
        )

    write_capture(capture, path)

    request_text = capture.source.text
    try:
        result = adapter.capture(source_text=request_text, case=case)
    except KeyboardInterrupt:
        capture = capture.model_copy(
            update={"state": "interrupted", "completed_at": utc_now()}
        )
        write_capture(capture, path)
        raise
    except Exception as exc:  # provider, transport, or configuration failure
        kind = getattr(exc, "capture_kind", "provider_error")
        capture = capture.model_copy(update={
            "state": kind if kind in ("configuration_error", "provider_error") else "provider_error",
            "completed_at": utc_now(),
            "error": CaptureError(kind=type(exc).__name__, message=str(exc)[:2000]),
        })
        write_capture(capture, path)
        raise CaptureFailure(str(exc), capture, path) from exc

    request, response, raw_text = result
    capture = capture.model_copy(update={
        "state": "received",
        "request": request,
        "response": response,
    })
    write_capture(capture, path)

    if response.stop_reason == "max_tokens":
        capture = capture.model_copy(update={
            "state": "truncated",
            "completed_at": utc_now(),
            "error": CaptureError(
                kind="truncated",
                message="response hit the output token limit; a partial review is not scored",
            ),
        })
        write_capture(capture, path)
        raise CaptureFailure("response truncated", capture, path)

    try:
        output = _parse(raw_text)
    except Exception as exc:
        capture = capture.model_copy(update={
            "state": "parse_error",
            "completed_at": utc_now(),
            "error": CaptureError(kind=type(exc).__name__, message=str(exc)[:2000]),
        })
        write_capture(capture, path)
        raise CaptureFailure(f"could not parse provider response: {exc}", capture, path) from exc

    capture = capture.model_copy(update={
        "state": "completed",
        "completed_at": utc_now(),
        "output": output,
        "output_sha256": text_sha256(output.model_dump_json()),
    })
    write_capture(capture, path)
    return capture.sealed()


def _parse(raw_text: str) -> ReviewOutput:
    start, end = raw_text.find("{"), raw_text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in response")
    return ReviewOutput.model_validate_json(raw_text[start : end + 1])
