"""Adapters for a matter: a deterministic stub, and an opt-in live model.

The prompt is assembled the same way for both, from the condition's template and the
documents that condition may see. The stub ignores it, but the experiment log hashes
it either way, so a prompt change is a recorded configuration change even offline.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any

from contract_eval.matter import LoadedMatter, MatterReview

STUB_MODEL = "stub-fixture"
DOCUMENTS_PLACEHOLDER = "{documents}"


class MatterFixtureMissing(FileNotFoundError):
    """No committed stub output exists for this round and condition."""


def render_documents(loaded: LoadedMatter, round_id: str, condition_id: str) -> str:
    blocks = []
    for document in loaded.matter.visible_documents(round_id, condition_id):
        blocks.append(
            f'<document id="{document.document_id}" kind="{document.kind}" '
            f'title="{document.title}">\n'
            f"{loaded.texts[document.document_id].rstrip()}\n"
            "</document>"
        )
    return "\n\n".join(blocks)


def render_prompt(loaded: LoadedMatter, round_id: str, condition_id: str) -> str:
    template = loaded.prompt_template(condition_id)
    if DOCUMENTS_PLACEHOLDER not in template:
        raise ValueError(
            f"prompt for condition {condition_id!r} has no {DOCUMENTS_PLACEHOLDER} "
            "placeholder, so the documents would never reach the model"
        )
    # replace, not format: contract text may contain braces.
    return template.replace(
        DOCUMENTS_PLACEHOLDER, render_documents(loaded, round_id, condition_id)
    )


CAPTURE_SCHEMA = "contract-review-eval.matter-capture.v1"


def load_review_file(path: Path) -> tuple[MatterReview, dict[str, Any]]:
    """Read a review, and what is known about where it came from.

    A capture written by a live run carries its matter, round, condition, model,
    effort and prompt hash. A bare output file carries nothing, and the caller treats
    it as an output of unknown origin.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("schema") == CAPTURE_SCHEMA:
        if data.get("status") == "failed" or "raw_text" not in data:
            raise ValueError(
                f"{path} records a failed attempt ({data.get('error_type')}); there "
                "is no output to score"
            )
        meta = {k: v for k, v in data.items() if k != "raw_text"}
        return MatterReview.model_validate_json(data["raw_text"]), meta
    if isinstance(data, dict) and "raw_text" in data:
        return MatterReview.model_validate_json(data["raw_text"]), {}
    return MatterReview.model_validate(data), {}


def parse_review_file(path: Path) -> MatterReview:
    return load_review_file(path)[0]


class StubMatterAdapter:
    identifier = STUB_MODEL
    model: str | None = STUB_MODEL
    effort: str | None = None

    def review(
        self, loaded: LoadedMatter, round_id: str, condition_id: str
    ) -> MatterReview:
        path = loaded.directory / "fixtures" / f"{round_id}.{condition_id}.json"
        if not path.is_file():
            raise MatterFixtureMissing(
                f"no stub fixture at {path.relative_to(loaded.root)}"
            )
        return parse_review_file(path)


class LiveMatterAdapter:
    """One request per round and condition. Every attempt leaves a capture."""

    identifier = "live"

    def __init__(
        self,
        model: str | None = None,
        client: Any | None = None,
        capture_dir: Path | None = Path("captures") / "matters",
    ) -> None:
        from contract_eval.adapters import live

        self._settings = live
        self._capture_dir = capture_dir
        if client is None:
            # Reuses the single-contract adapter's model resolution and key check
            # rather than holding a second copy of either.
            self.model = live.LiveAdapter(model=model).model
        else:
            self.model = model or os.environ.get("CONTRACT_EVAL_MODEL") or live.DEFAULT_MODEL
        self.effort = live._EFFORT
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run 'uv sync --extra live'."
            ) from exc
        return anthropic.Anthropic(
            max_retries=0, timeout=self._settings._TIMEOUT_SECONDS
        )

    def review(
        self, loaded: LoadedMatter, round_id: str, condition_id: str
    ) -> MatterReview:
        prompt = render_prompt(loaded, round_id, condition_id)
        client = self._resolve_client()
        try:
            message = client.messages.parse(
                model=self.model,
                max_tokens=self._settings._MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                output_format=MatterReview,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            # The SDK validates the response against the schema inside this call, so
            # a provider error, a truncated reply or an output that breaks the schema
            # can all surface here, before any text is returned. The attempt is still
            # recorded. An attempt that leaves no trace cannot be counted, and a set
            # of results with uncounted failures overstates the system.
            self._capture(loaded, round_id, condition_id, prompt, error=exc)
            raise

        raw_text = "".join(b.text for b in message.content if b.type == "text")
        self._capture(loaded, round_id, condition_id, prompt, raw_text=raw_text, message=message)
        if getattr(message, "stop_reason", None) == "max_tokens":
            raise RuntimeError(
                f"model response hit the {self._settings._MAX_TOKENS} token limit and "
                "is truncated; raise CONTRACT_EVAL_MAX_TOKENS rather than scoring a "
                "partial review"
            )
        return MatterReview.model_validate_json(raw_text)

    def _capture(
        self, loaded: LoadedMatter, round_id: str, condition_id: str, prompt: str,
        *, raw_text: str | None = None, message: Any = None,
        error: Exception | None = None,
    ) -> None:
        """Write what came back, or that nothing did.

        A returned capture can be scored later through `matter-evaluate --review`,
        which is how a run made before the answers were written is scored afterwards.
        """
        if self._capture_dir is None:
            return
        from contract_eval.capture import text_sha256

        usage = getattr(message, "usage", None)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory = loaded.root / self._capture_dir / loaded.matter.matter_id
        directory.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "schema": CAPTURE_SCHEMA,
            "status": "failed" if error is not None else "returned",
            "matter_id": loaded.matter.matter_id,
            "round_id": round_id,
            "condition_id": condition_id,
            "captured_at": stamp,
            "model": self.model,
            "returned_model": getattr(message, "model", None),
            "effort": self.effort,
            "stop_reason": getattr(message, "stop_reason", None),
            "request_id": getattr(message, "id", None),
            "input_tokens": getattr(usage, "input_tokens", None) if usage else None,
            "output_tokens": getattr(usage, "output_tokens", None) if usage else None,
            "prompt_sha256": text_sha256(prompt),
        }
        if error is not None:
            record["error_type"] = type(error).__name__
            record["error"] = str(error)
        else:
            record["raw_text_sha256"] = text_sha256(raw_text)
            record["raw_text"] = raw_text
        path = directory / f"{round_id}.{condition_id}.{stamp}.json"
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


def get_matter_adapter(live: bool, model: str | None = None):
    if live:
        return LiveMatterAdapter(model=model)
    return StubMatterAdapter()
