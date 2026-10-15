"""Adapter that runs an external program: the contract on stdin, `ReviewOutput` JSON on stdout.

A vendor can put its own product behind the harness with a few lines in any language,
without adding an SDK or credentials to this repository. The command is split with
`shlex` and run without a shell, so the string is never interpreted twice.
"""

import json
import os
import shlex
import subprocess

from pydantic import ValidationError

from contract_eval.capture import ProviderRequest, ProviderResponse, text_sha256
from contract_eval.models import ReviewOutput
from contract_eval.review_v2 import ReviewOutputV2

# A hung program must fail rather than stall a sequential run indefinitely.
_TIMEOUT_SECONDS = float(os.environ.get("CONTRACT_EVAL_TIMEOUT_SECONDS", "300"))
_STDERR_EXCERPT = 2000


class CommandAdapterError(RuntimeError):
    """The program could not be run, failed, or printed something that is not a review."""


def _split(command: str | None) -> list[str]:
    argv = shlex.split(command or "")
    if not argv:
        raise CommandAdapterError(
            "--adapter command needs --command, e.g. --command 'python my_reviewer.py'"
        )
    return argv


def identifier(command: str | None) -> str:
    """Recorded in provenance, so the command line must not carry secrets."""
    return "command:" + shlex.join(_split(command))


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= _STDERR_EXCERPT else "..." + text[-_STDERR_EXCERPT:]


class CommandAdapter:
    def __init__(self, command: str | None, timeout_seconds: float = _TIMEOUT_SECONDS) -> None:
        self.argv = _split(command)
        self.timeout_seconds = timeout_seconds
        self.model = identifier(command)

    def _run(self, source_text: str, case: str) -> str:
        # The case name is passed for wrappers that route by contract type; the
        # contract itself is the only input the review may depend on.
        env = {**os.environ, "CONTRACT_EVAL_CASE": case}
        try:
            result = subprocess.run(
                self.argv,
                input=source_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CommandAdapterError(f"command not found: {self.argv[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise CommandAdapterError(
                f"command timed out after {self.timeout_seconds:g}s: {self.argv[0]}"
            ) from exc
        if result.returncode != 0:
            stderr = _excerpt(result.stderr)
            raise CommandAdapterError(
                f"command exited with status {result.returncode}: {self.argv[0]}"
                + (f"\nstderr: {stderr}" if stderr else "")
            )
        return result.stdout

    def capture(
        self, source_text: str, case: str
    ) -> tuple[ProviderRequest, ProviderResponse, str]:
        raw_text = self._run(source_text, case)
        request = ProviderRequest(
            model=self.model,
            max_output_tokens=0,
            timeout_seconds=self.timeout_seconds,
            prompt=source_text,
            prompt_sha256=text_sha256(source_text),
        )
        response = ProviderResponse(raw_text=raw_text, raw_text_sha256=text_sha256(raw_text))
        return request, response, raw_text

    def review(self, source_text: str, case: str) -> ReviewOutput:
        _, _, raw_text = self.capture(source_text=source_text, case=case)
        return parse_output(raw_text)

    def review_v2(self, source_text: str, case: str) -> ReviewOutputV2:
        """The command contract is v1; it is upgraded on load, as the stub fixture is."""
        from contract_eval.upgrade import upgrade_review

        return upgrade_review(self.review(source_text=source_text, case=case))


def parse_output(raw_text: str) -> ReviewOutput:
    """Strict: the whole of stdout is one JSON document matching `ReviewOutput`."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise CommandAdapterError(
            f"command output is not valid JSON ({exc}); stdout began: {raw_text[:200]!r}"
        ) from exc
    try:
        return ReviewOutput.model_validate(data)
    except ValidationError as exc:
        raise CommandAdapterError(
            f"command output does not match the ReviewOutput schema: {exc}"
        ) from exc
