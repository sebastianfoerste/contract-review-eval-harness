"""Replay must reproduce a live score from captured bytes, without a provider."""

from pathlib import Path

import pytest

from contract_eval.adapters import get_adapter
from contract_eval.capture import read_capture, write_capture
from contract_eval.capture_runner import capture_attempt, new_run_id
from contract_eval.cli import evaluate_case
from contract_eval.replay import ReplayError, replay, verify_capture


def _capture(tmp_path, case="nda"):
    return capture_attempt(
        get_adapter(False), case=case, run_id=new_run_id(), out_dir=tmp_path,
        origin="stub", adapter_id="stub",
    )


def test_replay_reproduces_the_live_score_for_the_same_bytes(tmp_path):
    """The point of the pure scorer: one code path, two entry points."""
    capture = _capture(tmp_path)

    live = evaluate_case("nda", live=False)
    replayed = replay(capture, alias_modes=("on",))["scores"]["on"]

    assert replayed == live


def test_replay_is_byte_stable(tmp_path):
    capture = _capture(tmp_path)

    first = replay(capture, alias_modes=("on", "off"))
    second = replay(capture, alias_modes=("on", "off"))

    assert first["result_sha256"] == second["result_sha256"]
    assert first == second


def test_alias_modes_score_identical_bytes(tmp_path):
    capture = _capture(tmp_path)

    result = replay(capture, alias_modes=("on", "off"))

    assert set(result["scores"]) == {"on", "off"}
    assert result["provenance"]["parsed_output_sha256"] == capture.output_sha256


def test_tampered_capture_fails_before_scoring(tmp_path):
    capture = _capture(tmp_path)
    path = tmp_path / f"{capture.capture_id}.json"
    path.write_text(path.read_text().replace('"nda"', '"saas"', 1))

    with pytest.raises(ReplayError, match="integrity"):
        replay(read_capture(path))


def test_source_drift_fails_by_default_and_is_comparison_only_under_override(tmp_path):
    capture = _capture(tmp_path)
    drifted = capture.model_copy(
        update={"source": capture.source.model_copy(update={"text": capture.source.text + "\n"})}
    )
    # Re-seal so the capture stays internally consistent; only the working tree differs.
    drifted = drifted.model_copy(update={
        "source": drifted.source.model_copy(
            update={"sha256": __import__("contract_eval.capture", fromlist=["text_sha256"]).text_sha256(drifted.source.text)}
        )
    }).sealed()

    with pytest.raises(ReplayError, match="allow-input-drift"):
        replay(drifted)

    result = replay(drifted, allow_input_drift=True)
    assert result["eligible_for_certification"] is False
    assert result["provenance"]["comparison_only"] is True
    assert result["provenance"]["input_drift"]


def test_unscoreable_capture_is_authentic_but_refused(tmp_path):
    capture = _capture(tmp_path)
    truncated = capture.model_copy(
        update={"state": "truncated", "output": None, "output_sha256": None}
    ).sealed()
    path = tmp_path / "truncated.json"
    write_capture(truncated, path)

    report = verify_capture(read_capture(path))
    assert report["authentic"] is True
    assert report["scoreable"] is False

    with pytest.raises(ReplayError, match="no scoreable output"):
        replay(read_capture(path))


def test_replay_makes_no_network_call(tmp_path, monkeypatch):
    """Replay must work with the provider path removed entirely."""
    import contract_eval.adapters as adapters

    capture = _capture(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("replay attempted to construct an adapter")

    monkeypatch.setattr(adapters, "get_adapter", forbidden)
    result = replay(capture, alias_modes=("on",))

    assert result["scores"]["on"]["clause_f1"] > 0


def test_legacy_captures_reproduce_the_committed_report():
    """The published comparison must be derivable, not transcribed."""
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path("scripts").resolve()))
    from generate_live_run_report import SPEC, build  # noqa: E402

    committed = json.loads(
        Path("examples/live-run-claude-opus-5-2026-09-01.json").read_text()
    )
    spec = json.loads(SPEC.read_text())

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        regenerated = build(Path(tmp))

    assert regenerated["report_sha256"] == committed["report_sha256"]
    assert len(regenerated["rows"]) == len(spec["captures"]) * len(spec["alias_modes"])
    # Every legacy row is comparison-only: the gold sets have moved since the run.
    assert regenerated["comparison_only"] is True


def test_legacy_captures_are_authentic_and_marked_as_imports():
    from pathlib import Path

    from contract_eval.capture import read_capture
    from contract_eval.replay import verify_capture

    for path in sorted(Path("examples/captures").glob("legacy-*.json")):
        capture = read_capture(path)
        report = verify_capture(capture)

        assert report["authentic"], f"{path.name}: {report['errors']}"
        assert capture.origin == "legacy_file"
        # Provider provenance was never recorded for these; it must stay null.
        assert capture.request is None
        assert capture.response.request_id is None
        assert capture.response.stop_reason is None
