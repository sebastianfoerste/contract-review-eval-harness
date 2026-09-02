"""The adapter protocol.

`review()` is the original contract and stays: the robustness campaign calls it
thousands of times across mutated sources and has no use for capture envelopes.

`capture()` is the provenance-carrying path. It returns what was asked, what came
back, and the raw text, so the caller can persist evidence before parsing. `review()`
is a thin wrapper over it, which keeps one provider integration rather than two.
"""

from typing import Protocol

from contract_eval.capture import ProviderRequest, ProviderResponse
from contract_eval.models import ReviewOutput


class Adapter(Protocol):
    def review(self, source_text: str, case: str) -> ReviewOutput: ...

    def capture(
        self, source_text: str, case: str
    ) -> tuple[ProviderRequest, ProviderResponse, str]: ...
