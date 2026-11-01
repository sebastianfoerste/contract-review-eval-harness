"""The command adapter runs a vendor's program; every failure must name its cause."""

import json
import shlex
import sys
from pathlib import Path

import pytest

from contract_eval import paths
from contract_eval.adapters import AdapterChoice, adapter_identifier, get_adapter
from contract_eval.adapters.command import CommandAdapter, CommandAdapterError
from contract_eval.cases import ALL_CASES
from contract_eval.cli import evaluate_case, main
from contract_eval.models import ReviewOutput

# Echoes the stub fixture for the case it is asked about, so a review through the
# command adapter must score exactly as the stub does.
_ECHO_FIXTURE = """
import os, sys
from pathlib import Path
contract = sys.stdin.read()
assert contract.strip(), "the contract arrives on stdin"
fixtures = Path(sys.argv[1])
print((fixtures / f"{os.environ['CONTRACT_EVAL_CASE']}_stub.json").read_text())
"""


def _command(tmp_path: Path, body: str, *args: str) -> str:
    script = tmp_path / "reviewer.py"
    script.write_text(body, encoding="utf-8")
    return shlex.join([sys.executable, str(script), *args])


def _fixtures() -> str:
    return str(paths.project_root() / "fixtures")


def test_command_output_is_parsed_into_a_review(tmp_path):
    adapter = CommandAdapter(_command(tmp_path, _ECHO_FIXTURE, _fixtures()))
    review = adapter.review(source_text="CONTRACT TEXT", case="nda")

    fixture = json.loads((Path(_fixtures()) / "nda_stub.json").read_text(encoding="utf-8"))
    assert review == ReviewOutput.model_validate(fixture)


def test_non_zero_exit_reports_status_and_stderr(tmp_path):
    body = "import sys\nsys.stderr.write('vendor API refused the request')\nsys.exit(3)\n"
    adapter = CommandAdapter(_command(tmp_path, body))

    with pytest.raises(CommandAdapterError, match="status 3") as raised:
        adapter.review(source_text="x", case="nda")
    assert "vendor API refused the request" in str(raised.value)


def test_invalid_json_is_rejected(tmp_path):
    adapter = CommandAdapter(_command(tmp_path, "print('not json')\n"))

    with pytest.raises(CommandAdapterError, match="not valid JSON"):
        adapter.review(source_text="x", case="nda")


def test_schema_mismatch_is_rejected(tmp_path):
    adapter = CommandAdapter(_command(tmp_path, "print('{\"clauses\": 7}')\n"))

    with pytest.raises(CommandAdapterError, match="ReviewOutput schema"):
        adapter.review(source_text="x", case="nda")


def test_timeout_and_missing_program_fail_clearly(tmp_path):
    slow = CommandAdapter(_command(tmp_path, "import time\ntime.sleep(5)\n"), timeout_seconds=0.5)
    with pytest.raises(CommandAdapterError, match="timed out"):
        slow.review(source_text="x", case="nda")

    missing = CommandAdapter(str(tmp_path / "no-such-reviewer"))
    with pytest.raises(CommandAdapterError, match="command not found"):
        missing.review(source_text="x", case="nda")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX execute permission")
def test_a_program_that_cannot_be_executed_fails_clearly(tmp_path, capsys):
    script = tmp_path / "reviewer.sh"
    script.write_text("#!/bin/sh\necho '{}'\n", encoding="utf-8")
    script.chmod(0o644)  # no execute bit: the OS refuses to run it

    with pytest.raises(CommandAdapterError, match="command could not be run"):
        CommandAdapter(str(script)).review(source_text="x", case="nda")

    # The CLI reports it as an error line, not a traceback.
    with pytest.raises(SystemExit) as exited:
        main(["evaluate", "--adapter", "command", "--command", str(script), "--out", str(tmp_path)])
    assert exited.value.code == 1
    captured = capsys.readouterr()
    assert "Error: command could not be run" in captured.err
    assert "Error:" not in captured.out


def test_command_is_split_without_a_shell(tmp_path):
    # A shell would expand this; shlex hands it to the program as one literal argument.
    body = "import sys\nprint(sys.argv[1], file=sys.stderr)\nsys.exit(1)\n"
    adapter = CommandAdapter(_command(tmp_path, body, "$HOME; echo injected"))

    with pytest.raises(CommandAdapterError) as raised:
        adapter.review(source_text="x", case="nda")
    assert "$HOME; echo injected" in str(raised.value)


def test_missing_command_is_a_configuration_error():
    with pytest.raises(CommandAdapterError, match="needs --command"):
        get_adapter(False, choice=AdapterChoice(name="command"))


def test_command_adapter_scores_like_the_stub(tmp_path):
    choice = AdapterChoice(name="command", command=_command(tmp_path, _ECHO_FIXTURE, _fixtures()))

    assert evaluate_case("nda", live=False, adapter=choice) == evaluate_case("nda", live=False)
    assert adapter_identifier(False, choice=choice).startswith("command:")


def test_cli_adapter_command_runs_evaluate_end_to_end(tmp_path, capsys):
    command = _command(tmp_path, _ECHO_FIXTURE, _fixtures())
    out = tmp_path / "out"

    main(["evaluate", "--case", "all", "--adapter", "command", "--command", command,
          "--out", str(out), "--format", "json"])

    assert "wrote" in capsys.readouterr().out
    scores = json.loads((out / "scorecard.json").read_text())["scores"]
    assert set(scores) == set(ALL_CASES)
    provenance = json.loads((out / "run-provenance.json").read_text())
    assert provenance["adapter"] == "command:" + command


def test_cli_reports_a_failing_command_without_a_traceback(tmp_path, capsys):
    command = _command(tmp_path, "import sys\nsys.exit(2)\n")

    with pytest.raises(SystemExit) as exited:
        main(["evaluate", "--adapter", "command", "--command", command, "--out", str(tmp_path)])

    assert exited.value.code == 1
    captured = capsys.readouterr()
    assert "Error: command exited with status 2" in captured.err
    assert "Error:" not in captured.out
