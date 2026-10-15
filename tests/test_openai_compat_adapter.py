"""The OpenAI-compatible adapter against a local fake server: no key, no internet."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from contract_eval import paths
from contract_eval.adapters import AdapterChoice, adapter_identifier, get_adapter
from contract_eval.adapters.openai_compat import ConfigurationError, OpenAICompatibleAdapter
from contract_eval.capture import TokenPrices
from contract_eval.capture_runner import capture_attempt, new_run_id
from contract_eval.models import ReviewOutput

_KEY_ENV = "CONTRACT_EVAL_TEST_OPENAI_KEY"


def _fixture_text() -> str:
    return (paths.project_root() / "fixtures" / "nda_stub.json").read_text(encoding="utf-8")


@pytest.fixture
def server(monkeypatch):
    """A Chat Completions fake on 127.0.0.1 that records what it was sent."""
    # A proxy configured in the environment must not intercept the loopback fake.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    seen: list[dict] = []
    reply = {"status": 200, "finish_reason": "stop"}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", "0"))
            seen.append({
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": json.loads(self.rfile.read(length)),
            })
            if reply["status"] != 200:
                payload = {"error": {"message": "model not found"}}
            else:
                payload = {
                    "id": "chatcmpl-test",
                    "model": "fake-model-2026",
                    "choices": [{
                        "index": 0,
                        "finish_reason": reply["finish_reason"],
                        # Fenced, as some compatible servers return it despite the prompt.
                        "message": {"role": "assistant",
                                    "content": "```json\n" + _fixture_text() + "\n```"},
                    }],
                    "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
                }
            data = json.dumps(payload).encode("utf-8")
            self.send_response(reply["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"base_url": f"http://127.0.0.1:{httpd.server_port}/v1", "seen": seen, "reply": reply}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_request_path_and_no_auth_header_without_a_key(server, monkeypatch):
    monkeypatch.delenv(_KEY_ENV, raising=False)
    adapter = OpenAICompatibleAdapter(model="fake-model", base_url=server["base_url"], api_key_env=_KEY_ENV)

    review = adapter.review(source_text="CONTRACT TEXT", case="nda")

    assert review == ReviewOutput.model_validate_json(_fixture_text())
    (request,) = server["seen"]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] is None
    assert request["body"]["model"] == "fake-model"
    assert "CONTRACT TEXT" in request["body"]["messages"][0]["content"]
    assert request["body"]["response_format"]["type"] == "json_schema"


def test_bearer_header_is_sent_when_the_key_variable_is_set(server, monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "sk-test-not-a-real-key")
    adapter = OpenAICompatibleAdapter(model="fake-model", base_url=server["base_url"], api_key_env=_KEY_ENV)

    request, response, _ = adapter.capture(source_text="CONTRACT TEXT", case="nda")

    assert server["seen"][0]["authorization"] == "Bearer sk-test-not-a-real-key"
    # The key never reaches the capture.
    assert "sk-test" not in request.model_dump_json() + response.model_dump_json()
    assert response.request_id == "chatcmpl-test"
    assert response.returned_model == "fake-model-2026"
    assert (response.input_tokens, response.output_tokens) == (1200, 300)


def test_length_finish_is_treated_as_truncation(server):
    server["reply"]["finish_reason"] = "length"
    adapter = OpenAICompatibleAdapter(model="fake-model", base_url=server["base_url"])

    with pytest.raises(RuntimeError, match="token limit"):
        adapter.review(source_text="x", case="nda")


def test_http_error_names_the_status(server):
    server["reply"]["status"] = 404
    adapter = OpenAICompatibleAdapter(model="fake-model", base_url=server["base_url"])

    with pytest.raises(RuntimeError, match="HTTP 404"):
        adapter.review(source_text="x", case="nda")


def test_capture_records_latency_and_cost_at_supplied_prices(server, tmp_path):
    choice = AdapterChoice(name="openai-compatible", base_url=server["base_url"])
    adapter = get_adapter(False, model="fake-model", choice=choice)
    prices = TokenPrices(usd_per_million_input_tokens=2.0, usd_per_million_output_tokens=10.0)

    capture = capture_attempt(
        adapter, case="nda", run_id=new_run_id(), out_dir=tmp_path, origin="live",
        adapter_id=adapter_identifier(False, "fake-model", choice=choice), prices=prices,
    )

    assert capture.state == "completed"
    assert capture.latency_seconds is not None and capture.latency_seconds >= 0
    assert capture.cost is not None
    assert capture.cost.prices == prices
    assert capture.cost.estimated_cost == pytest.approx((1200 * 2.0 + 300 * 10.0) / 1_000_000)
    written = json.loads(Path(tmp_path / f"{capture.capture_id}.json").read_text())
    assert written["cost"]["prices"]["usd_per_million_output_tokens"] == 10.0
    assert capture.integrity_ok()


def test_missing_model_fails_before_any_request(server):
    with pytest.raises(ConfigurationError, match="needs --model"):
        get_adapter(False, choice=AdapterChoice(name="openai-compatible", base_url=server["base_url"]))
    assert server["seen"] == []


def test_identifier_names_model_and_endpoint():
    choice = AdapterChoice(name="openai-compatible", base_url="http://127.0.0.1:11434/v1/")
    assert adapter_identifier(False, "llama3", choice=choice) == (
        "openai-compatible:llama3@http://127.0.0.1:11434/v1"
    )
