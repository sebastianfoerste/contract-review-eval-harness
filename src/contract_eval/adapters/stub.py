"""Deterministic adapter that returns a fixture. No network, no API key."""

import json
from pathlib import Path

from contract_eval.models import ReviewOutput


class StubAdapter:
    def __init__(self, fixtures_dir: Path = Path("fixtures")) -> None:
        self._dir = fixtures_dir

    def review(self, source_text: str, case: str) -> ReviewOutput:
        data = json.loads((self._dir / f"{case}_stub.json").read_text())
        return ReviewOutput.model_validate(data)
