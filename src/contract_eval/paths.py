"""Where the bundled cases are read from.

A repository checkout keeps the cases in top-level folders, and every committed
certificate and report records its inputs by those relative paths. An installed wheel
carries byte-identical copies under `contract_eval/_bundled/` (see the hatch
`force-include` table in pyproject.toml), so a bundled case also runs without a
checkout, for example through `uvx`.

Resolution order, first match wins:

    1. the working directory, when it holds data/, expected/ and fixtures/
    2. the checkout this package was installed from in editable mode
    3. the copy shipped inside the wheel

The first rule is what every command did before the wheel carried the cases, so a
checkout behaves exactly as it did. The layout helpers below are the only place that
spells out a case's file names.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

CASE_DIRECTORIES: tuple[str, ...] = ("data", "expected", "fixtures")
CAMPAIGN_FILE = "robustness/campaign.v1.json"
DRAFTS_DIRECTORY = "annotations/drafts"
BUNDLE_DIRECTORY = "_bundled"


def source_file(case: str) -> str:
    """The synthetic contract, relative to the case root."""
    return f"data/{case}_sample.md"


def gold_file(case: str) -> str:
    """The hand-authored answer set, relative to the case root."""
    return f"expected/{case}.json"


def fixture_file(case: str) -> str:
    """The deterministic stub output, relative to the case root."""
    return f"fixtures/{case}_stub.json"


def is_case_root(path: Path) -> bool:
    return all((path / name).is_dir() for name in CASE_DIRECTORIES)


def checkout_root() -> Path | None:
    """The repository this module was imported from, if it is one.

    Only an editable install or a direct `src/` import resolves to a checkout. In an
    installed wheel the same parent is a `lib/` directory with no pyproject.toml.
    """
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").is_file() and is_case_root(candidate):
        return candidate
    return None


def _package_directory() -> object:
    return resources.files("contract_eval")


def bundled_root() -> Path | None:
    """The copy inside an installed wheel, or None in a checkout.

    A wheel installs as plain files, so the package directory is a real path. A
    zipped import would not be, and is not supported.
    """
    package = _package_directory()
    if not isinstance(package, Path):
        return None
    bundle = package / BUNDLE_DIRECTORY
    return bundle if is_case_root(bundle) else None


def project_root() -> Path:
    """The directory that holds the bundled cases, resolved on every call."""
    working = Path(".")
    if is_case_root(working):
        return working
    for candidate in (checkout_root(), bundled_root()):
        if candidate is not None:
            return candidate
    raise FileNotFoundError(
        "no bundled cases found: run from a repository checkout, or reinstall the "
        "contract-eval wheel, which ships the cases inside the package"
    )


def resolve_root(root: Path | None) -> Path:
    return project_root() if root is None else root


def resolve_input(path: Path, root: Path | None = None) -> Path:
    """Find a relative default such as robustness/campaign.v1.json.

    A path that exists as given, or is absolute, is returned unchanged. Otherwise it
    is looked up inside the case root, so the default campaign also resolves from an
    installed wheel.
    """
    if path.is_absolute() or path.exists():
        return path
    candidate = resolve_root(root) / path
    return candidate if candidate.exists() else path
