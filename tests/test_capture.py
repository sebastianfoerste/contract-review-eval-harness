"""Every terminal state must leave evidence, and only `completed` may be scored."""

from pathlib import Path

import pytest

from contract_eval.adapters import get_adapter
from contract_eval.capture import ProviderRequest, ProviderResponse, read_capture, text_sha256
from contract_eval.capture_runner import CaptureFailure, capture_attempt, new_run_id


def _run(adapter, tmp_path, case="nda"):
    return capture_attempt(
        adapter, case=case, run_id=new_run_id(), out_dir=tmp_path,
        origin="stub", adapter_id="test",
    )


class _Adapter:
    """Minimal adapter whose single attempt is scripted by the test."""

    def __init__(self, raw_text="{}", stop_reason="end_turn", raises=None):
        self._raw, self._stop, self._raises = raw_text, stop_reason, raises

    def capture(self, source_text, case):
        if self._raises:
            raise self._raises
        prompt = "p"
        return (
            ProviderRequest(
                model="m", max_output_tokens=10, prompt=prompt,
                prompt_sha256=text_sha256(prompt),
            ),
            ProviderResponse(
                raw_text=self._raw, raw_text_sha256=text_sha256(self._raw),
                stop_reason=self._stop,
            ),
            self._raw,
        )


def test_completed_capture_is_sealed_and_scoreable(tmp_path):
    capture = _run(get_adapter(False), tmp_path)

    assert capture.state == "completed"
    assert capture.is_scoreable()
    assert capture.integrity_ok()
    assert capture.output_sha256
    assert read_capture(tmp_path / f"{capture.capture_id}.json").integrity_ok()


def test_truncated_response_is_preserved_and_never_scored(tmp_path):
    with pytest.raises(CaptureFailure) as excinfo:
        _run(_Adapter(raw_text='{"clauses":[]', stop_reason="max_tokens"), tmp_path)

    capture = excinfo.value.capture
    assert capture.state == "truncated"
    assert not capture.is_scoreable()
    # The raw bytes survive so the truncation can be diagnosed.
    assert capture.response.raw_text == '{"clauses":[]'
    assert read_capture(excinfo.value.path).state == "truncated"


def test_malformed_response_is_preserved_as_parse_error(tmp_path):
    with pytest.raises(CaptureFailure) as excinfo:
        _run(_Adapter(raw_text="not json at all"), tmp_path)

    capture = excinfo.value.capture
    assert capture.state == "parse_error"
    assert not capture.is_scoreable()
    assert capture.response.raw_text == "not json at all"
    assert capture.output is None


def test_provider_error_leaves_a_terminal_capture(tmp_path):
    with pytest.raises(CaptureFailure) as excinfo:
        _run(_Adapter(raises=RuntimeError("connection reset")), tmp_path)

    capture = excinfo.value.capture
    assert capture.state == "provider_error"
    assert capture.error.message == "connection reset"
    assert capture.output is None


def test_interrupt_is_recorded_and_re_raised(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        _run(_Adapter(raises=KeyboardInterrupt()), tmp_path)

    captures = list(tmp_path.glob("*.json"))
    assert len(captures) == 1
    assert read_capture(captures[0]).state == "interrupted"


def test_tampering_with_one_byte_breaks_integrity(tmp_path):
    capture = _run(get_adapter(False), tmp_path)
    path = tmp_path / f"{capture.capture_id}.json"

    tampered = path.read_text().replace('"case": "nda"', '"case": "saas"', 1)
    path.write_text(tampered)

    assert not read_capture(path).integrity_ok()


def test_capture_never_records_credentials(tmp_path):
    """The request is recorded without headers or environment values."""
    capture = _run(get_adapter(False), tmp_path)
    blob = (tmp_path / f"{capture.capture_id}.json").read_text().lower()

    for forbidden in ("api_key", "authorization", "bearer", "x-api-key", "sk-ant"):
        assert forbidden not in blob


def test_write_is_atomic_and_leaves_no_partial_file(tmp_path):
    """A failed write must not replace a good capture with a half-written one."""
    import contract_eval.capture as capture_module

    capture = _run(get_adapter(False), tmp_path)
    path = tmp_path / f"{capture.capture_id}.json"
    good = path.read_text()

    original = capture_module.json.dumps

    def explode(*args, **kwargs):
        raise OSError("disk full")

    capture_module.json.dumps = explode
    try:
        with pytest.raises(OSError):
            capture_module.write_capture(capture, path)
    finally:
        capture_module.json.dumps = original

    assert path.read_text() == good, "the previous capture must survive a failed write"
    assert not list(tmp_path.glob(".*.json.*")), "no temporary file may be left behind"
