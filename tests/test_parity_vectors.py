"""The committed parity vectors pin scorer output that the TypeScript port must reproduce."""
from pathlib import Path
import shutil

import pytest

from contract_eval.cases import ALL_CASES
from contract_eval.models import ReviewOutput
from contract_eval.web_export import (
    PARITY_VECTORS_PATH, SCENARIOS, apply_scenario, build_parity_vectors,
    check_parity_vectors, write_parity_vectors,
)

ROOT = Path(__file__).resolve().parents[1]


def test_committed_vectors_match_the_current_scorer():
    # A failure means the scorer or a fixture changed. Run `make parity-vectors`,
    # commit the diff, then run `make web-export` so the web port is retested.
    check_parity_vectors(ROOT)


def test_every_case_and_scenario_is_covered():
    vectors = build_parity_vectors(ROOT)
    scenario_vectors = [v for v in vectors if "scenario" in v]
    assert {v["caseId"] for v in vectors} == set(ALL_CASES)
    assert len(scenario_vectors) == len(ALL_CASES) * len(SCENARIOS) * 2
    assert len(vectors) - len(scenario_vectors) == len(ALL_CASES) * 2


def test_conflicting_flags_adds_one_contradicting_severity():
    review = ReviewOutput.model_validate_json((ROOT / "fixtures" / "nda_stub.json").read_bytes())
    output = apply_scenario(review, "conflicting-flags")
    added = output.risk_flags[-1]
    assert len(output.risk_flags) == len(review.risk_flags) + 1
    assert added.clause_type == review.risk_flags[0].clause_type
    assert added.severity != review.risk_flags[0].severity


def test_unknown_scenario_is_rejected():
    with pytest.raises(ValueError):
        apply_scenario(ReviewOutput(clauses=[], risk_flags=[], citations=[]), "typo")


@pytest.fixture
def workspace(tmp_path):
    for folder in ("data", "expected", "fixtures"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    (tmp_path / "examples").mkdir()
    return tmp_path


def test_missing_vectors_are_rejected(workspace):
    with pytest.raises(ValueError, match="missing"):
        check_parity_vectors(workspace)


def test_changed_fixture_is_detected(workspace):
    write_parity_vectors(workspace)
    check_parity_vectors(workspace)
    stub = workspace / "fixtures" / "nda_stub.json"
    review = ReviewOutput.model_validate_json(stub.read_bytes())
    review.citations = []
    stub.write_text(review.model_dump_json())
    with pytest.raises(ValueError, match="differs"):
        check_parity_vectors(workspace)
    assert (workspace / PARITY_VECTORS_PATH).is_file()
