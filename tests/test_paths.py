"""The cases resolve from a checkout first and from the wheel's bundled copy otherwise.

The bundle is assembled here from the force-include table in pyproject.toml, the same
table the wheel build reads, so a path missing from that table fails this test rather
than an installed user's first run.
"""

import json
import shutil
import tomllib
from pathlib import Path

import pytest

from contract_eval import paths
from contract_eval.cases import ALL_CASES
from contract_eval.cli import evaluate_case
from contract_eval.reference_evidence import EVIDENCE
from contract_eval.release_certificate import build_release_certificate

ROOT = Path(__file__).resolve().parents[1]


def _force_include() -> dict[str, str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]


def _install_fake_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Lay out the package as the wheel would, then hide the checkout."""
    package = tmp_path / "site-packages" / "contract_eval"
    for source, target in _force_include().items():
        destination = tmp_path / "site-packages" / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / source).is_dir():
            shutil.copytree(ROOT / source, destination)
        else:
            shutil.copyfile(ROOT / source, destination)
    monkeypatch.setattr(paths, "_package_directory", lambda: package)
    monkeypatch.setattr(paths, "checkout_root", lambda: None)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    return package / paths.BUNDLE_DIRECTORY


def test_a_checkout_resolves_to_the_working_directory_as_before():
    assert paths.project_root() == Path(".")


def test_outside_the_checkout_an_editable_install_finds_its_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert paths.project_root() == ROOT
    assert evaluate_case("nda", live=False)["hallucination_count"] == 1


def test_without_a_checkout_the_bundled_copy_reproduces_the_committed_certificate(
    tmp_path, monkeypatch
):
    committed = json.loads((ROOT / "examples" / "release-certificate.json").read_text())
    bundle = _install_fake_bundle(tmp_path, monkeypatch)

    assert paths.project_root() == bundle
    scores = {case: evaluate_case(case, live=False) for case in ALL_CASES}
    # Identical bytes under identical relative paths: the bundle is not a second
    # benchmark, it is the same one.
    assert build_release_certificate(scores) == committed


def test_the_default_campaign_resolves_into_the_bundle(tmp_path, monkeypatch):
    bundle = _install_fake_bundle(tmp_path, monkeypatch)

    resolved = paths.resolve_input(Path(paths.CAMPAIGN_FILE))

    assert resolved == bundle / paths.CAMPAIGN_FILE
    assert resolved.is_file()


def test_no_cases_anywhere_fails_with_a_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "checkout_root", lambda: None)
    monkeypatch.setattr(paths, "bundled_root", lambda: None)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="no bundled cases found"):
        paths.project_root()


def test_resolve_input_leaves_existing_and_absolute_paths_alone(tmp_path):
    assert paths.resolve_input(Path("pyproject.toml")) == Path("pyproject.toml")
    absolute = tmp_path / "missing.json"
    assert paths.resolve_input(absolute) == absolute
    assert paths.resolve_input(Path("no/such/file.json")) == Path("no/such/file.json")


def test_the_wheel_ships_every_input_the_resolver_serves():
    shipped = _force_include()
    for name in (*paths.CASE_DIRECTORIES, paths.CAMPAIGN_FILE, paths.DRAFTS_DIRECTORY):
        assert shipped.get(name) == f"contract_eval/{paths.BUNDLE_DIRECTORY}/{name}", name
    # Frozen reference evidence changes which gold the obligation path loads. Once it
    # exists, a wheel without it would quietly score against the draft instead.
    if (ROOT / EVIDENCE).exists():
        assert EVIDENCE.as_posix() in shipped, "ship the reference evidence in the wheel"


def test_layout_helpers_match_the_paths_committed_certificates_record():
    certificate = json.loads((ROOT / "examples" / "release-certificate.json").read_text())
    for result in certificate["cases"]:
        manifest, case = result["input_manifest"], result["case"]
        assert manifest["source_contract"]["path"] == paths.source_file(case)
        assert manifest["expected_answer"]["path"] == paths.gold_file(case)
        assert manifest["adapter_output"]["path"] == paths.fixture_file(case)
