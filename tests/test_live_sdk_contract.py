"""The live adapter's call surface against the installed Anthropic SDK.

The SDK is an optional extra, so this module is skipped where it is absent. CI
installs `--all-extras`, so it runs there, at the locked version. The same file run
against the declared floor in pyproject.toml is what makes that floor honest:

    uv run --isolated --no-project --with "anthropic==<floor>" --with pydantic \\
        --with pytest --with-editable . pytest -q tests/test_live_sdk_contract.py

Nothing here touches the network. The client is replaced with a recorder, so the
test sees the keyword arguments the adapter really passes rather than a copy of them,
and binds those to the real `Messages.parse` signature.
"""

from __future__ import annotations

import inspect
import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")

from contract_eval.adapters import live  # noqa: E402
from contract_eval.adapters.live import LiveAdapter, parse_kwargs  # noqa: E402
from contract_eval.models import ReviewOutput  # noqa: E402
from contract_eval.review_v2 import ReviewOutputV2  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# None on an SDK below the floor, so the floor test reports that rather than the
# module failing to import.
PARSE = getattr(anthropic.resources.messages.Messages, "parse", None)
# Captured before any test replaces `anthropic.Anthropic` with the recorder below.
REAL_CLIENT = anthropic.Anthropic
KEYWORDS = ("model", "max_tokens", "thinking", "output_config", "output_format", "messages")


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".")[:3])


def _declared_floor() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    (requirement,) = pyproject["project"]["optional-dependencies"]["live"]
    match = re.fullmatch(r"anthropic>=(\d+\.\d+\.\d+)", requirement)
    assert match, f"the live extra must pin a plain floor, got {requirement!r}"
    return match.group(1)


def _parse():
    assert PARSE is not None, (
        f"anthropic {anthropic.__version__} has no non-beta Messages.parse; the live "
        f"extra needs {_declared_floor()} or later"
    )
    return PARSE


def test_the_installed_sdk_satisfies_the_declared_floor() -> None:
    assert _version(anthropic.__version__) >= _version(_declared_floor())
    _parse()


def test_parse_takes_no_catch_all_keywords() -> None:
    """A `**kwargs` on `parse` would make the binding test below vacuous."""
    kinds = {p.kind for p in inspect.signature(_parse()).parameters.values()}
    assert inspect.Parameter.VAR_KEYWORD not in kinds


@pytest.mark.parametrize("output_format", [ReviewOutput, ReviewOutputV2])
def test_every_keyword_the_adapter_passes_binds_to_parse(output_format: type) -> None:
    kwargs = parse_kwargs("claude-test", "CONTRACT: ...", output_format)
    assert set(kwargs) == set(KEYWORDS)

    parameters = inspect.signature(_parse()).parameters
    missing = sorted(key for key in kwargs if key not in parameters)
    assert not missing, f"the installed anthropic {anthropic.__version__} has no {missing}"
    # `bind` also fails if the SDK has grown a required keyword the adapter omits.
    inspect.signature(_parse()).bind(object(), **kwargs)


def _fake_message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="msg_test",
        model="claude-test-returned",
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


class _RecordingClient:
    """Stands in for `anthropic.Anthropic`: records the call, returns a parsed reply.

    The constructor keyword arguments are passed to the real client, so a release
    that drops `max_retries` or `timeout` fails here rather than on the first live run.
    """

    calls: list[dict] = []
    constructed: list[dict] = []

    def __init__(self, **kwargs: object) -> None:
        self.constructed.append(kwargs)
        REAL_CLIENT(api_key="test-key", **kwargs)
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        payload = {
            "clauses": [{"clause_type": "term", "text": "perpetual"}],
            "risk_flags": [],
            "citations": [{"quote": "shall remain in effect in perpetuity", "clause_type": "term"}],
            "abstentions": [],
        }
        return _fake_message(json.dumps(payload))


@pytest.fixture
def recording_client(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingClient]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(anthropic, "Anthropic", _RecordingClient)
    _RecordingClient.calls = []
    _RecordingClient.constructed = []
    return _RecordingClient


def test_capture_sends_exactly_the_helper_kwargs(recording_client: type[_RecordingClient]) -> None:
    adapter = LiveAdapter(model="claude-test")
    request, response, raw_text = adapter.capture("CONTRACT TEXT", "nda")

    assert recording_client.constructed == [{"max_retries": 0, "timeout": live._TIMEOUT_SECONDS}]
    (call,) = recording_client.calls
    assert call == parse_kwargs("claude-test", live._PROMPT.format(source="CONTRACT TEXT"), ReviewOutput)
    inspect.signature(_parse()).bind(object(), **call)

    assert request.model == "claude-test"
    assert response.returned_model == "claude-test-returned"
    assert response.input_tokens == 11 and response.output_tokens == 7
    assert ReviewOutput.model_validate_json(raw_text).clauses[0].clause_type == "term"


def test_review_v2_asks_for_the_v2_schema(recording_client: type[_RecordingClient]) -> None:
    adapter = LiveAdapter(model="claude-test")
    with pytest.raises(Exception):
        # The recorder's v1 reply does not validate as v2; the call itself is what is checked.
        adapter.review_v2("CONTRACT TEXT", "nda")
    (call,) = recording_client.calls
    assert call["output_format"] is ReviewOutputV2
    assert call["messages"] == [{"role": "user", "content": live._PROMPT_V2.format(source="CONTRACT TEXT")}]


def test_missing_sdk_message_names_both_install_forms() -> None:
    assert "uv sync --extra live" in live._MISSING_SDK
    assert 'pip install "contract-eval[live]"' in live._MISSING_SDK
