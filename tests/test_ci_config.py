"""Offline checks on the supply-chain settings of the workflows and the composite action.

action.yml runs in other people's CI, so a moved tag there reaches them too. Every
third-party action is pinned to a full commit SHA with its release in a comment, which
Dependabot updates together. PyYAML is not a dependency, so the files are read as text.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
ACTION_FILES = [*WORKFLOWS, ROOT / "action.yml"]

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)(.*)$", re.MULTILINE)
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
RELEASE_COMMENT = re.compile(r"^\s+# v\d+\.\d+\.\d+\s*$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_third_party_action_is_pinned_to_a_commit_sha() -> None:
    unpinned = []
    for path in ACTION_FILES:
        for ref, rest in USES.findall(_read(path)):
            if ref.startswith("./"):
                continue
            if not (PINNED.match(ref) and RELEASE_COMMENT.match(rest)):
                unpinned.append(f"{path.relative_to(ROOT)}: {ref}{rest}")
    assert not unpinned, f"pin to a full SHA with a '# vX.Y.Z' comment: {unpinned}"


def test_setup_uv_installs_a_fixed_uv_version() -> None:
    for path in WORKFLOWS:
        text = _read(path)
        assert not re.search(r"^\s*version:\s*[\"']?latest", text, re.MULTILINE), path.name
        for step in re.split(r"\n\s*- name:", text):
            if "astral-sh/setup-uv@" in step:
                assert re.search(r"^\s*version:\s*\"\d+\.\d+\.\d+\"", step, re.MULTILINE), (
                    f"{path.name}: setup-uv without a fixed uv version"
                )


def test_ci_installs_from_the_lockfile() -> None:
    syncs = re.findall(r"uv sync[^\n]*", _read(ROOT / ".github" / "workflows" / "ci.yml"))
    assert syncs
    assert all("--locked" in line for line in syncs), syncs


def test_ci_checks_the_lockfile_before_installing() -> None:
    text = _read(ROOT / ".github" / "workflows" / "ci.yml")
    assert "run: uv lock --check" in text
    assert text.index("uv lock --check") < text.index("uv sync"), "check the lock before syncing"


def test_workflows_default_to_a_read_only_token() -> None:
    for path in WORKFLOWS:
        assert re.search(r"^permissions:\n  contents: read\n", _read(path), re.MULTILINE), path.name
