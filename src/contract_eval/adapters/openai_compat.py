"""Optional adapter for any OpenAI-compatible Chat Completions endpoint.

OpenAI, Mistral, vLLM, Ollama and others serve the same `/chat/completions` shape, so
one adapter with a configurable base URL covers them. It uses `urllib` rather than an
SDK: no new dependency, nothing to import on the default offline path, and a test can
point it at a local fake server.
"""

import json
import os
import urllib.error
import urllib.request

from pydantic import BaseModel

from contract_eval.adapters.live import _PROMPT, _PROMPT_V2
from contract_eval.capture import ProviderRequest, ProviderResponse, text_sha256
from contract_eval.models import ReviewOutput
from contract_eval.review_v2 import ReviewOutputV2

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
_MAX_TOKENS = int(os.environ.get("CONTRACT_EVAL_MAX_TOKENS", "16000"))
# OpenAI's reasoning models reject `max_tokens` and require `max_completion_tokens`;
# most other compatible servers only know `max_tokens`. The field is named per run.
_MAX_TOKENS_FIELD = os.environ.get("CONTRACT_EVAL_MAX_TOKENS_FIELD", "max_tokens")
_TIMEOUT_SECONDS = float(os.environ.get("CONTRACT_EVAL_TIMEOUT_SECONDS", "300"))
_ERROR_EXCERPT = 500

# Not every compatible server enforces `response_format`, so the schema is also stated
# in the prompt. The Anthropic prompt needs neither: there the schema is the request.
_SCHEMA_SUFFIX = """
Respond with a single JSON object and nothing else. It must match this JSON schema:
{schema}
"""


class ConfigurationError(RuntimeError):
    capture_kind = "configuration_error"


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Make a redirect an HTTPError instead of following it.

    urllib copies a request's headers onto the redirected request, so following one
    would send the API key to whichever host the response names. A Chat Completions
    POST has nothing to follow anyway: urllib would replay it as a GET without a body.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirect)


def resolve_base_url(base_url: str | None) -> str:
    return (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def identifier(model: str | None, base_url: str | None) -> str:
    """Model and endpoint both: the same model id served by two hosts is two runs."""
    if not model:
        raise ConfigurationError("--adapter openai-compatible needs --model")
    return f"openai-compatible:{model}@{resolve_base_url(base_url)}"


def _parse(raw_text: str, schema: type[BaseModel]) -> BaseModel:
    # The same tolerance as the capture parser: a compatible server may wrap the
    # object in a code fence even when asked not to.
    start, end = raw_text.find("{"), raw_text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in response")
    return schema.model_validate_json(raw_text[start : end + 1])


class OpenAICompatibleAdapter:
    def __init__(
        self,
        model: str | None,
        base_url: str | None = None,
        api_key_env: str | None = None,
        timeout_seconds: float = _TIMEOUT_SECONDS,
    ) -> None:
        identifier(model, base_url)  # fail on a missing model before any request
        self.model: str = model  # type: ignore[assignment]
        self.base_url = resolve_base_url(base_url)
        # Only the variable's name is held. The key itself is read per request and
        # never stored, logged or written into a capture.
        self.api_key_env = api_key_env or DEFAULT_API_KEY_ENV
        self.timeout_seconds = timeout_seconds

    def _complete(
        self, prompt: str, schema: type[BaseModel]
    ) -> tuple[ProviderRequest, ProviderResponse, str]:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            _MAX_TOKENS_FIELD: _MAX_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
            },
        }
        http_request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        api_key = os.environ.get(self.api_key_env)
        if api_key:  # local servers such as Ollama need none
            # Unredirected: never copied onto another request, whatever the opener.
            http_request.add_unredirected_header("Authorization", f"Bearer {api_key}")
        try:
            with _OPENER.open(http_request, timeout=self.timeout_seconds) as reply:
                data = json.loads(reply.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise RuntimeError(
                    f"{self.base_url}/chat/completions redirected (HTTP {exc.code}) to "
                    f"{exc.headers.get('Location')}; redirects are not followed, so the "
                    "API key stays with the configured host. Pass the final endpoint as --base-url."
                ) from exc
            detail = exc.read().decode("utf-8", errors="replace")[:_ERROR_EXCERPT]
            raise RuntimeError(
                f"{self.base_url}/chat/completions returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"could not reach {self.base_url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{self.base_url} returned a non-JSON body: {exc}") from exc

        try:
            choice = data["choices"][0]
            raw_text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("response has no choices[0].message.content") from exc
        usage = data.get("usage") or {}
        finish_reason = choice.get("finish_reason")

        request = ProviderRequest(
            model=self.model,
            max_output_tokens=_MAX_TOKENS,
            timeout_seconds=self.timeout_seconds,
            prompt=prompt,
            prompt_sha256=text_sha256(prompt),
        )
        response = ProviderResponse(
            raw_text=raw_text,
            raw_text_sha256=text_sha256(raw_text),
            request_id=data.get("id"),
            returned_model=data.get("model"),
            # Normalised so the capture runner's truncation check, written against
            # Anthropic's stop reason, catches a cut-off response here too.
            stop_reason="max_tokens" if finish_reason == "length" else finish_reason,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
        return request, response, raw_text

    def capture(
        self, source_text: str, case: str
    ) -> tuple[ProviderRequest, ProviderResponse, str]:
        prompt = _PROMPT.format(source=source_text) + _SCHEMA_SUFFIX.format(
            schema=json.dumps(ReviewOutput.model_json_schema())
        )
        return self._complete(prompt, ReviewOutput)

    def _checked(self, response: ProviderResponse) -> None:
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                f"model response hit the {_MAX_TOKENS} token limit and is truncated; "
                "raise CONTRACT_EVAL_MAX_TOKENS rather than scoring a partial review"
            )

    def review(self, source_text: str, case: str) -> ReviewOutput:
        _, response, raw_text = self.capture(source_text=source_text, case=case)
        self._checked(response)
        return _parse(raw_text, ReviewOutput)  # type: ignore[return-value]

    def review_v2(self, source_text: str, case: str) -> ReviewOutputV2:
        prompt = _PROMPT_V2.format(source=source_text) + _SCHEMA_SUFFIX.format(
            schema=json.dumps(ReviewOutputV2.model_json_schema())
        )
        _, response, raw_text = self._complete(prompt, ReviewOutputV2)
        self._checked(response)
        return _parse(raw_text, ReviewOutputV2)  # type: ignore[return-value]
