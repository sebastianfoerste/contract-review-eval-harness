"""Optional live adapter (Anthropic). Imported lazily — never required for the default offline path."""

import os

from contract_eval.models import ReviewOutput

_MODEL = "claude-opus-4-8"

_PROMPT = """You are a contract review assistant. Read the contract below and return ONLY valid JSON of this shape:
{{
  "clauses": [{{"clause_type": "snake_case_type", "text": "short description"}}],
  "risk_flags": [{{"clause_type": "...", "severity": "low|medium|high", "rationale": "..."}}],
  "citations": [{{"quote": "text copied verbatim from the contract", "clause_type": "..."}}]
}}
Every citation quote MUST be copied verbatim from the contract. Do not invent text.

CONTRACT:
{source}
"""


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response.")
    return text[start : end + 1]


class LiveAdapter:
    def __init__(self) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            try:
                from pathlib import Path
                env_path = Path(__file__).resolve().parents[3] / ".env"
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == "ANTHROPIC_API_KEY":
                                os.environ["ANTHROPIC_API_KEY"] = v.strip().strip('"').strip("'")
                                break
            except Exception:
                pass

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Live mode needs it; "
                "run without --live to use the deterministic stub."
            )

    def review(self, source_text: str, case: str) -> ReviewOutput:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run 'uv add anthropic' to use "
                "--live, or run without --live for the deterministic stub."
            ) from exc

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": _PROMPT.format(source=source_text)}],
        )
        text = "".join(block.text for block in message.content if block.type == "text")
        return ReviewOutput.model_validate_json(_extract_json(text))
