"""Immutable record of one adapter attempt.

A score is only auditable if the exact bytes it was computed from survive. Before
captures, a live evaluation parsed a provider response, scored it, and discarded the
response; a published number could not be recomputed without calling the provider
again and getting different text back.

The capture is written before the provider is called and rewritten as the attempt
progresses, so a truncated, malformed or interrupted attempt leaves evidence rather
than nothing. Scoring only ever reads a `completed` capture.

    [started] -> [received] -> [completed] -> scoring
        |            |
        |            +-> truncated | parse_error   (never scored)
        +-> configuration_error | provider_error | interrupted
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from contract_eval.models import ReviewOutput

CAPTURE_SCHEMA: Final = "contract-review-eval.captured-review.v1"
RUN_MANIFEST_SCHEMA = "contract-review-eval.capture-run-manifest.v1"

CaptureOrigin = Literal["live", "stub", "legacy_file"]
CaptureState = Literal[
    "started",
    "configuration_error",
    "provider_error",
    "received",
    "truncated",
    "parse_error",
    "interrupted",
    "completed",
]

_OPTIONAL_MEASUREMENTS = ("latency_seconds", "cost")

# States that carry a scoreable, fully parsed review. Everything else is evidence of
# an attempt and must never reach the scorer.
SCOREABLE_STATES: frozenset[str] = frozenset({"completed"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Snapshot(BaseModel):
    """An input embedded in the capture so replay never depends on the working tree."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    text: str


class ProviderRequest(BaseModel):
    """What was asked of the provider. Never carries credentials or headers."""

    model_config = ConfigDict(extra="forbid")

    model: str
    max_output_tokens: int
    timeout_seconds: float | None = None
    prompt: str
    prompt_sha256: str
    # Reasoning effort changes the output, and it can be set per run from the
    # environment without a code change, so a capture that omitted it could not
    # explain a score difference between two runs of the same commit. Optional:
    # captures written before the field existed, and adapters that call no model,
    # carry None.
    effort: str | None = None


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = None
    raw_text_sha256: str | None = None
    request_id: str | None = None
    returned_model: str | None = None
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class TokenPrices(BaseModel):
    """User-supplied prices. Never defaulted: a vendor price list in code goes stale."""

    model_config = ConfigDict(extra="forbid")

    usd_per_million_input_tokens: float = Field(ge=0)
    usd_per_million_output_tokens: float = Field(ge=0)

    @classmethod
    def from_env(cls) -> "TokenPrices | None":
        """Read CONTRACT_EVAL_USD_PER_MTOK_INPUT and _OUTPUT; None unless both are set."""
        raw_in = os.environ.get("CONTRACT_EVAL_USD_PER_MTOK_INPUT")
        raw_out = os.environ.get("CONTRACT_EVAL_USD_PER_MTOK_OUTPUT")
        if not raw_in or not raw_out:
            return None
        return cls(
            usd_per_million_input_tokens=float(raw_in),
            usd_per_million_output_tokens=float(raw_out),
        )


class CostEstimate(BaseModel):
    """An estimate, with the prices and token counts it was computed from.

    Carrying the inputs makes the number reproducible from the capture alone, and
    makes plain which price list a published cost assumed.
    """

    model_config = ConfigDict(extra="forbid")

    currency: Literal["USD"] = "USD"
    prices: TokenPrices
    input_tokens: int
    output_tokens: int
    estimated_cost: float


def estimate_cost(response: "ProviderResponse", prices: TokenPrices | None) -> CostEstimate | None:
    """None when no price is configured or the provider reported no token counts."""
    if prices is None or response.input_tokens is None or response.output_tokens is None:
        return None
    cost = (
        response.input_tokens * prices.usd_per_million_input_tokens
        + response.output_tokens * prices.usd_per_million_output_tokens
    ) / 1_000_000
    return CostEstimate(
        prices=prices,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        estimated_cost=round(cost, 8),
    )


class CaptureError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    message: str


class CapturedReview(BaseModel):
    """One adapter attempt, start to terminal state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.captured-review.v1"] = Field(
        default=CAPTURE_SCHEMA, alias="schema"
    )
    capture_id: str
    run_id: str
    origin: CaptureOrigin
    state: CaptureState

    case: str
    scenario_id: str | None = None
    variant: Literal["original", "mutated"] = "original"
    run_index: int = 0

    started_at: str
    completed_at: str | None = None

    adapter_id: str
    prompt_version: str
    parser_version: str
    repository_commit: str | None = None

    source: Snapshot
    gold: Snapshot | None = None

    request: ProviderRequest | None = None
    response: ProviderResponse = Field(default_factory=ProviderResponse)

    output: ReviewOutput | None = None
    output_sha256: str | None = None

    error: CaptureError | None = None

    # Wall-clock seconds around the adapter call, and the cost it implies at the
    # prices the user supplied. Both are omitted from the serialised capture while
    # unset, so captures written before they existed keep their bytes and digests.
    latency_seconds: float | None = None
    cost: CostEstimate | None = None

    integrity_sha256: str | None = None

    @model_serializer(mode="wrap")
    def _omit_unset_measurements(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        for key in _OPTIONAL_MEASUREMENTS:
            if data.get(key) is None:
                data.pop(key, None)
        return data

    def payload_without_integrity(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True)
        data.pop("integrity_sha256", None)
        return data

    def sealed(self) -> "CapturedReview":
        """Return a copy carrying its own canonical digest."""
        return self.model_copy(
            update={"integrity_sha256": canonical_sha256(self.payload_without_integrity())}
        )

    def integrity_ok(self) -> bool:
        return self.integrity_sha256 == canonical_sha256(self.payload_without_integrity())

    def is_scoreable(self) -> bool:
        return self.state in SCOREABLE_STATES and self.output is not None


def write_capture(capture: CapturedReview, path: Path) -> Path:
    """Seal and write a capture atomically.

    The temporary file lives in the destination directory so the rename cannot cross
    a filesystem boundary, and it is flushed and fsynced before the rename. An
    interrupted write therefore leaves either the previous capture or the new one,
    never a truncated file that still parses as valid JSON.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    sealed = capture.sealed()
    blob = json.dumps(
        sealed.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False
    ) + "\n"

    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    )
    try:
        handle.write(blob)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return path


def read_capture(path: Path) -> CapturedReview:
    return CapturedReview.model_validate_json(path.read_text(encoding="utf-8"))


def snapshot_of(path: Path, *, root: Path = Path(".")) -> Snapshot:
    text = (root / path).read_text(encoding="utf-8")
    return Snapshot(path=str(path), sha256=text_sha256(text), text=text)
