"""Deterministic adapter that returns a fixture. No network, no API key."""

import json
from pathlib import Path

from contract_eval.capture import ProviderRequest, ProviderResponse, text_sha256
from contract_eval.models import ReviewOutput
from contract_eval.review_v2 import ReviewOutputV2

STUB_MODEL = "stub-fixture"


class StubAdapter:
    def __init__(self, fixtures_dir: Path = Path("fixtures")) -> None:
        self._dir = fixtures_dir

    def capture(
        self, source_text: str, case: str
    ) -> tuple[ProviderRequest, ProviderResponse, str]:
        """Return the fixture through the same contract the live adapter uses.

        The stub goes through the capture path so replay, verification and the
        capture tests exercise the production code path rather than a shortcut that
        only the offline suite ever runs.
        """
        raw_text = (self._dir / f"{case}_stub.json").read_text(encoding="utf-8")
        prompt = f"stub fixture for case {case}"
        request = ProviderRequest(
            model=STUB_MODEL,
            max_output_tokens=0,
            timeout_seconds=None,
            prompt=prompt,
            prompt_sha256=text_sha256(prompt),
        )
        response = ProviderResponse(
            raw_text=raw_text,
            raw_text_sha256=text_sha256(raw_text),
            returned_model=STUB_MODEL,
            stop_reason="end_turn",
        )
        return request, response, raw_text

    def review(self, source_text: str, case: str) -> ReviewOutput:
        data = json.loads((self._dir / f"{case}_stub.json").read_text())
        return ReviewOutput.model_validate(data)

    def review_v2(self, source_text: str, case: str) -> ReviewOutputV2:
        """The same fixture in evidence-linked form.

        Derived mechanically from the v1 stub by scripts/convert_stubs_to_v2.py, so
        the deliberate imperfections are identical and the two paths stay comparable.
        """
        data = json.loads((self._dir / f"{case}_stub.v2.json").read_text())
        return ReviewOutputV2.model_validate(data)
