"""Offline checks on README.md, which is also the PyPI long description.

PyPI renders the README without the repository around it, so a relative link or image
breaks there. Every link is therefore absolute, and a link into this repository must
name a file that exists on `main`. The README stays short; detail lives in docs/.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MAX_WORDS = 350

REPO = "sebastianfoerste/contract-review-eval-harness"
REPO_FILE_LINK = re.compile(
    rf"^https://(?:github\.com/{REPO}/blob/main|raw\.githubusercontent\.com/{REPO}/main)/([^#?]+)(?:#([^?]*))?"
)

FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
# `](target)` catches every inline link and image, including the outer link of a
# nested badge such as [![CI](badge)](target).
INLINE_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_TARGET = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE)
HTML_TARGET = re.compile(r"""\b(?:href|src)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _link_targets(markdown: str) -> list[str]:
    text = INLINE_CODE.sub("", FENCE.sub("", markdown))
    return (
        INLINE_TARGET.findall(text)
        + REFERENCE_TARGET.findall(text)
        + HTML_TARGET.findall(text)
    )


def _heading_anchors(markdown: str) -> set[str]:
    """GitHub's anchors for the headings of a markdown file."""
    anchors = set()
    for line in FENCE.sub("", markdown).splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if match:
            anchors.add(re.sub(r"[^\w\- ]", "", match.group(1).lower()).replace(" ", "-"))
    return anchors


def test_readme_is_at_most_350_words() -> None:
    words = len(_readme().split())
    assert words <= MAX_WORDS, f"README.md has {words} words; move detail into docs/ (limit {MAX_WORDS})"


def test_readme_has_no_relative_links() -> None:
    targets = _link_targets(_readme())
    assert targets, "no links found; the link pattern no longer matches the README"
    relative = [t for t in targets if not re.match(r"^(https?:|mailto:)", t, re.IGNORECASE)]
    assert not relative, f"README.md must use absolute links so it renders on PyPI: {relative}"


def test_readme_repository_links_point_to_existing_files() -> None:
    checked, broken = 0, []
    for target in _link_targets(_readme()):
        match = REPO_FILE_LINK.match(target)
        if not match:
            continue
        checked += 1
        path, fragment = ROOT / match.group(1), match.group(2)
        if not path.is_file():
            broken.append(target)
        elif fragment and path.suffix == ".md":
            if fragment not in _heading_anchors(path.read_text(encoding="utf-8")):
                broken.append(target)
    assert checked, "no links into the repository found; the link pattern no longer matches"
    assert not broken, f"README.md links to missing files or headings: {broken}"


def test_readme_scorecard_excerpt_is_copied_from_the_committed_scorecard() -> None:
    """Every table row in the README is a verbatim row of examples/scorecard.md."""
    committed = set((ROOT / "examples" / "scorecard.md").read_text(encoding="utf-8").splitlines())
    rows = [line for line in _readme().splitlines() if line.startswith("|")]
    assert len(rows) >= 5, rows
    missing = [row for row in rows if row not in committed]
    assert not missing, f"README rows that differ from examples/scorecard.md: {missing}"


def test_readme_keeps_the_safety_line() -> None:
    assert "Offline, deterministic, no API key. Synthetic contracts only. Not legal advice." in _readme()
