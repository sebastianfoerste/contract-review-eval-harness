"""The adapter protocol: anything that can produce a ReviewOutput for a contract."""

from typing import Protocol

from contract_eval.models import ReviewOutput


class Adapter(Protocol):
    def review(self, source_text: str, case: str) -> ReviewOutput: ...
