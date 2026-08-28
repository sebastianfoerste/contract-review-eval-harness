"""Adapter factory."""

from contract_eval.adapters.base import Adapter
from contract_eval.adapters.stub import StubAdapter


def get_adapter(live: bool, model: str | None = None) -> Adapter:
    if live:
        from contract_eval.adapters.live import LiveAdapter  # lazy: no SDK/key needed offline

        return LiveAdapter(model=model)
    return StubAdapter()


def adapter_identifier(live: bool, model: str | None = None) -> str:
    """Name the adapter that produced a result, for the run history and scorecards."""
    if not live:
        return "stub"
    from contract_eval.adapters.live import DEFAULT_MODEL

    import os

    return model or os.environ.get("CONTRACT_EVAL_MODEL") or DEFAULT_MODEL
