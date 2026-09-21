"""A final package version requires the verified evidence chain, not file presence."""
from pathlib import Path
import tomllib
from packaging.version import Version
from contract_eval.reference_evidence import reference_status
from contract_eval.cases import ALL_CASES

ROOT = Path(__file__).resolve().parents[1]


def test_reference_gate_covers_every_case():
    status = reference_status(ROOT)
    assert ALL_CASES
    assert [row["case"] for row in status["cases"]] == list(ALL_CASES)
    assert status["stage"] != "invalid", status["errors"]


def test_final_release_requires_verified_independent_evidence():
    version = Version(tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"])
    if not version.is_prerelease:
        status = reference_status(ROOT)
        assert status["finalReleaseEligible"], f"{version} cannot be final: {status}"
