"""The declared version may not shed its pre-release marker while the second
annotation is outstanding.

The decision, taken 2026-09-06: a plain v0.7.0 reads as a validated benchmark, and the
inter-annotator agreement figure that would justify that reading cannot exist until
Annotator B returns and the disagreements are adjudicated. Until then the honest version
carries an rc.

Nothing else holds this line. CI has no release step, the repository has no deployments
and no environments, and releases are cut by hand, so without a test the rc suffix reads
as an oversight waiting to be tidied away.

What this can and cannot prove: a return is a file on disk, and a ledger proves the
comparison ran against frozen bytes. Whether a human actually adjudicated each
disagreement is not mechanically visible. A green run here permits a release rather than
blessing one.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.version import Version

from contract_eval.annotators import SECOND
from contract_eval.cases import ALL_CASES

ROOT = Path(__file__).resolve().parents[1]
RETURNED = ROOT / "annotations" / "returned" / SECOND.slot
LEDGERS = ROOT / "annotations" / "ledgers"


def _declared_version() -> Version:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return Version(pyproject["project"]["version"])


def _missing_returns() -> list[str]:
    return [
        case
        for case in ALL_CASES
        if not (RETURNED / f"{case}.{SECOND.slot}.v2.json").is_file()
    ]


def _missing_ledgers() -> list[str]:
    return [case for case in ALL_CASES if not (LEDGERS / f"{case}.ledger.md").is_file()]


def test_the_guard_covers_at_least_one_case() -> None:
    # A guard that iterates an empty set passes without checking anything. That is the
    # instrument-that-cannot-fail failure, and it belongs nowhere in this repository.
    assert ALL_CASES


def test_version_stays_pre_release_while_the_second_annotation_is_outstanding() -> None:
    missing = _missing_returns()
    if not missing:
        return

    version = _declared_version()
    assert version.is_prerelease, (
        f"pyproject declares {version}, a final release, but Annotator B has not "
        f"returned {', '.join(missing)}. The version claims a validated benchmark that "
        f"nothing yet validates. Keep the rc until the return is in and adjudicated."
    )


def test_a_final_version_requires_the_comparison_to_have_run() -> None:
    version = _declared_version()
    if version.is_prerelease:
        return

    missing_returns = _missing_returns()
    assert not missing_returns, (
        f"{version} is a final release, but Annotator B's return is missing for "
        f"{', '.join(missing_returns)}."
    )

    missing_ledgers = _missing_ledgers()
    assert not missing_ledgers, (
        f"{version} is a final release and the returns are present, but no disagreement "
        f"ledger exists for {', '.join(missing_ledgers)}. Run "
        f"scripts/compare_annotations.py and adjudicate every row before releasing."
    )
