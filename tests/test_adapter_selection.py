"""`--adapter` selection, the `--live` alias, and the measurements every capture carries."""

import json

import pytest

from contract_eval import adapters
from contract_eval.adapters import AdapterChoice, adapter_choice, adapter_identifier, get_adapter
from contract_eval.adapters.stub import StubAdapter
from contract_eval.capture import ProviderResponse, TokenPrices, estimate_cost, read_capture
from contract_eval.capture_runner import capture_attempt, new_run_id
from contract_eval.cli import build_parser


@pytest.mark.parametrize("command", ["evaluate", "robustness", "evaluate-obligations"])
def test_live_and_adapter_anthropic_resolve_identically(command, monkeypatch):
    built: list[str | None] = []

    class FakeLive:
        """Stands in for the Anthropic adapter so no key or network is needed."""

        def __init__(self, model=None):
            built.append(model)

    monkeypatch.setattr("contract_eval.adapters.live.LiveAdapter", FakeLive)
    parser = build_parser()
    via_alias = parser.parse_args([command, "--live", "--model", "m-1"])
    via_name = parser.parse_args([command, "--adapter", "anthropic", "--model", "m-1"])

    resolved = []
    for args in (via_alias, via_name):
        adapter = get_adapter(args.live, model=args.model, choice=adapter_choice(args))
        identifier = adapter_identifier(args.live, args.model, choice=adapter_choice(args))
        resolved.append((type(adapter), identifier))

    assert resolved[0] == resolved[1] == (FakeLive, "m-1")
    assert built == ["m-1", "m-1"]


def test_live_cannot_be_combined_with_another_adapter():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["evaluate", "--live", "--adapter", "command"])


def test_default_and_legacy_calls_still_pick_the_stub():
    assert isinstance(get_adapter(False), StubAdapter)
    assert adapter_identifier(False) == "stub"
    args = build_parser().parse_args(["evaluate"])
    assert isinstance(get_adapter(args.live, choice=adapter_choice(args)), StubAdapter)
    assert adapters.adapter_name(False, AdapterChoice(name="stub")) == "stub"


def test_stub_capture_records_latency_and_no_cost_without_prices(tmp_path, monkeypatch):
    monkeypatch.delenv("CONTRACT_EVAL_USD_PER_MTOK_INPUT", raising=False)
    monkeypatch.delenv("CONTRACT_EVAL_USD_PER_MTOK_OUTPUT", raising=False)

    capture = capture_attempt(
        get_adapter(False), case="nda", run_id=new_run_id(), out_dir=tmp_path,
        origin="stub", adapter_id="stub",
    )

    assert capture.latency_seconds is not None and capture.latency_seconds >= 0
    assert capture.cost is None
    on_disk = read_capture(tmp_path / f"{capture.capture_id}.json")
    assert on_disk.integrity_ok()
    assert "cost" not in json.loads((tmp_path / f"{capture.capture_id}.json").read_text())


def test_cost_needs_prices_and_token_counts(monkeypatch):
    prices = TokenPrices(usd_per_million_input_tokens=3.0, usd_per_million_output_tokens=15.0)
    counted = ProviderResponse(input_tokens=1_000_000, output_tokens=100_000)

    assert estimate_cost(counted, None) is None
    assert estimate_cost(ProviderResponse(), prices) is None
    assert estimate_cost(counted, prices).estimated_cost == pytest.approx(4.5)

    monkeypatch.setenv("CONTRACT_EVAL_USD_PER_MTOK_INPUT", "3")
    monkeypatch.delenv("CONTRACT_EVAL_USD_PER_MTOK_OUTPUT", raising=False)
    assert TokenPrices.from_env() is None
    monkeypatch.setenv("CONTRACT_EVAL_USD_PER_MTOK_OUTPUT", "15")
    assert TokenPrices.from_env() == prices


def test_captures_without_measurements_keep_their_serialised_form(tmp_path):
    """Committed captures predate latency and cost; their digests must still verify."""
    capture = capture_attempt(
        get_adapter(False), case="nda", run_id=new_run_id(), out_dir=tmp_path,
        origin="stub", adapter_id="stub",
    )
    legacy = capture.model_copy(update={"latency_seconds": None, "cost": None}).sealed()
    payload = legacy.model_dump(mode="json", by_alias=True)

    assert "latency_seconds" not in payload and "cost" not in payload
    assert type(legacy).model_validate(payload).integrity_ok()
