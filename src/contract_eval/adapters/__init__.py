"""Adapter factory."""

from contract_eval.adapters.base import Adapter
from contract_eval.adapters.stub import StubAdapter


def get_adapter(live: bool) -> Adapter:
    if live:
        from contract_eval.adapters.live import LiveAdapter  # lazy: no SDK/key needed offline

        return LiveAdapter()
    return StubAdapter()
