"""Every statutory citation the harness authors has a row in docs/legal-currency.md.

The gold sets are human legal judgement, and their rationales cite provisions. Nothing
used to record when, or against what, a citation was last checked. The ledger does;
this test keeps it complete: a citation added to a gold set, a draft, a fixture, the
robustness campaign, a contract or a guide without a ledger row fails here.

Model output under examples/ is not a repository claim and is not scanned. Nothing
here touches the network: the ledger's URLs are checked by a reader, not by code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "legal-currency.md"

# Harness-authored text that may state a legal proposition.
SCANNED_GLOBS = (
    "expected/*.json",
    "candidates/expected/*.json",
    "annotations/drafts/*.json",
    "annotations/pack/**/*.md",
    "annotations/README.md",
    "candidates/README.md",
    "fixtures/*_stub.json",
    "robustness/*.json",
    "data/*.md",
    "candidates/data/*.md",
    "docs/*.md",
    "CASE_STUDY.md",
    "CHANGELOG.md",
    "README.md",
    "CONTRIBUTING.md",
    "scripts/build_annotation_pack.py",
)
EXCLUDED = {LEDGER}

# One pattern per citation style found in the repository. Each has a `kind` group so
# the normaliser knows how to spell it.
PATTERNS = (
    # Art. 28, Art. 28(3), Art. 28(3)(d); also the "and 28(3)(d)" continuation form.
    re.compile(r"(?P<art>Art\.\s?\d+(?:\(\d+\))*(?:\([a-z]\))?)"),
    re.compile(r"(?P<article>Article\s\d+)"),
    re.compile(r"(?P<chapter>Chapter\s[IVX]+)(?![A-Za-z])"),
    # § 130(1), §§ 130, 305 and 307 (an enumeration lists every number).
    re.compile(r"(?P<para>§§?\s?\d+(?:\(\d+\))?(?:(?:,\s?|\s(?:and|und)\s)\d+(?:\(\d+\))?)*)"),
    # "section 311 (1) of the German Civil Code (BGB)", possibly wrapped over a line.
    re.compile(r"(?P<section>section\s\d+\s*\(\d+\))", re.IGNORECASE),
    re.compile(r"(?P<regulation>Regulation \(EU\) \d{4}/\d+)"),
    re.compile(r"(?P<guidelines>Guidelines \d{2}/\d{4})"),
    re.compile(r"(?P<opinion>Opinion \d{1,2}/\d{4})"),
    # "lit. g", "lit. a to h": the DPA material's shorthand for Art. 28(3) points.
    re.compile(r"(?P<lit>lit\.\s?[a-z](?:\sto\s[a-z])?)(?![a-z])"),
)


def _normalise(kind: str, text: str) -> list[str]:
    """Spell a raw citation the way the ledger's first column does."""
    text = " ".join(text.split())
    if kind == "art":
        return [text.replace("Art.", "Art. ").replace("  ", " ")]
    if kind == "article":
        return ["Art. " + text.split()[1]]
    if kind == "chapter":
        return [text]
    if kind == "para":
        numbers = re.findall(r"\d+(?:\(\d+\))?", text)
        return [f"§ {number} BGB" for number in numbers]
    if kind == "section":
        number, subsection = re.match(r"section\s(\d+)\s*\((\d+)\)", text, re.IGNORECASE).groups()
        return [f"§ {number}({subsection}) BGB"]
    if kind == "lit":
        letters = re.findall(r"\b[a-z]\b", text.replace("lit.", ""))
        first, last = letters[0], letters[-1]
        return [f"Art. 28(3)({chr(code)})" for code in range(ord(first), ord(last) + 1)]
    return [text]


def extract_citations(text: str) -> list[str]:
    """Every normalised citation in `text`, in order of appearance, without duplicates."""
    found: list[str] = []
    for pattern in PATTERNS:
        for match in pattern.finditer(text):
            kind = match.lastgroup
            assert kind is not None
            for citation in _normalise(kind, match.group(kind)):
                if citation not in found:
                    found.append(citation)
    return found


def ledger_provisions(markdown: str) -> list[str]:
    """The first cell of every table row of the ledger, backticks removed."""
    cells = []
    for line in markdown.splitlines():
        if not line.startswith("| "):
            continue
        first = line.split("|")[1].strip().replace("`", "")
        if first and first != "Instrument and provision" and not set(first) <= set("-: "):
            cells.append(first)
    return cells


def _pattern(citation: str) -> re.Pattern[str]:
    """`Art. 2` must not match `Art. 28`; a bare `§ 130 BGB` is covered by `§ 130(1) BGB`."""
    bare = re.fullmatch(r"§ (\d+) BGB", citation)
    if bare:
        return re.compile(rf"§ {bare.group(1)}(?:\(\d+\))? BGB")
    return re.compile(re.escape(citation) + r"(?!\d)")


def _covers(cell: str, citation: str) -> bool:
    return _pattern(citation).search(cell) is not None


def missing_from_ledger(citations: list[str], provisions: list[str]) -> list[str]:
    return [c for c in citations if not any(_covers(cell, c) for cell in provisions)]


def _scanned_files() -> list[Path]:
    files: set[Path] = set()
    for pattern in SCANNED_GLOBS:
        files.update(p for p in ROOT.glob(pattern) if p.is_file())
    return sorted(files - EXCLUDED)


def test_the_ledger_exists_with_the_expected_columns() -> None:
    text = LEDGER.read_text(encoding="utf-8")
    header = "| Instrument and provision | Used in | What the repo says | Current position | Official source | Verified on | Status |"
    assert header in text, "the ledger table must keep its columns"
    assert "## Watch list" in text


def test_every_ledger_row_is_dated_sourced_and_classified() -> None:
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| Instrument") or set(line) <= set("|-: "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        assert len(cells) == 7, line
        provision, _, _, _, source, verified_on, status = cells
        assert re.search(r"https://[^\s)]+", source), f"no official URL for {provision}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_on), f"no verified-on date for {provision}"
        assert status in {"OK", "WATCH", "NEEDS OWNER REVIEW"}, f"unknown status for {provision}: {status}"


@pytest.mark.parametrize("path", _scanned_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_citation_in_harness_text_has_a_ledger_row(path: Path) -> None:
    citations = extract_citations(path.read_text(encoding="utf-8"))
    provisions = ledger_provisions(LEDGER.read_text(encoding="utf-8"))
    missing = missing_from_ledger(citations, provisions)
    assert not missing, (
        f"{path.relative_to(ROOT)} cites {missing} but docs/legal-currency.md has no row for them; "
        "add a dated, sourced row rather than deleting the citation"
    )


def test_the_scan_finds_the_known_gold_citations() -> None:
    """A scanner that silently found nothing would pass forever."""
    dpa = (ROOT / "expected" / "dpa.json").read_text(encoding="utf-8")
    found = extract_citations(dpa)
    for expected in ("Art. 28(3)(d)", "Art. 28(2)", "Art. 33(2)", "Chapter V", "Art. 46", "Regulation (EU) 2016/679"):
        assert expected in found, found
    nda = (ROOT / "expected" / "nda.json").read_text(encoding="utf-8")
    assert "§ 130(1) BGB" in extract_citations(nda)


def test_the_guard_bites_on_an_unlisted_citation() -> None:
    """Probe the extractor and the matcher on a string, not on a tracked file."""
    provisions = ledger_provisions(LEDGER.read_text(encoding="utf-8"))
    sample = (
        "Art. 28(3)(d) requires this; Article 99 and § 999(1) BGB and Chapter XIV, "
        "section 311 (1) of the German Civil Code (BGB), Guidelines 07/2020, lit. a to c."
    )
    citations = extract_citations(sample)
    assert citations == [
        "Art. 28(3)(d)", "Art. 99", "Chapter XIV", "§ 999(1) BGB", "§ 311(1) BGB",
        "Guidelines 07/2020", "Art. 28(3)(a)", "Art. 28(3)(b)", "Art. 28(3)(c)",
    ]
    assert missing_from_ledger(citations, provisions) == ["Art. 99", "Chapter XIV", "§ 999(1) BGB"]
    # A number must not be matched as a prefix of a longer one.
    assert missing_from_ledger(["Art. 2"], ["GDPR Art. 28(2)"]) == ["Art. 2"]
    assert missing_from_ledger(["§ 130 BGB"], ["§ 130(1) BGB"]) == []
