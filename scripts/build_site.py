"""Render the committed evidence into a static site for GitHub Pages.

    python scripts/build_site.py               # writes site/
    python scripts/build_site.py --out public

The site is a reading copy of files CI already verifies, so it adds no claim of its
own: each page is one committed Markdown file rendered to HTML, and the robustness
report, already a self-contained HTML file, is copied byte for byte.

Only the standard library is used, because the build has to run offline and a
Markdown package would be a new dependency for a handful of constructs. The
renderer covers what these files use (headings, paragraphs, pipe tables, lists,
fenced and inline code, links, bold and italic) and escapes every piece of source
text, so a quote lifted from a contract can never become markup on the page.
Output carries no build time, so the same inputs produce the same bytes.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "site"
SITE_TITLE = "contract-review-eval-harness"
REPOSITORY_URL = "https://github.com/sebastianfoerste/contract-review-eval-harness"


@dataclass(frozen=True)
class Page:
    source: str
    output: str
    title: str
    summary: str


PAGES: tuple[Page, ...] = (
    Page(
        "examples/scorecard.md",
        "scorecard.html",
        "Scorecard",
        "The deterministic stub reviewing the synthetic NDA, scored and gated.",
    ),
    Page(
        "examples/release-certificate.md",
        "release-certificate.html",
        "Release certificate",
        "The release policy's decision across every bundled case, with its failure register.",
    ),
    Page(
        "examples/live-run-claude-opus-5-2026-09-01.md",
        "live-run-claude-opus-5-2026-09-01.html",
        "Live run, 2026-09-01",
        "One captured model run, re-scored offline with aliases off and on.",
    ),
    Page(
        "examples/leaderboard.md",
        "leaderboard.html",
        "Leaderboard",
        "Every committed review output re-scored and decided by the release policy.",
    ),
)

# Already a complete, self-contained page; copied as-is so its digest still matches.
COPIED: tuple[Page, ...] = (
    Page(
        "examples/adversarial-robustness-report.html",
        "adversarial-robustness-report.html",
        "Adversarial robustness report",
        "How the scorer holds up against reviews built to game it.",
    ),
)

STYLE = """
body { font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  color: #1f2328; background: #ffffff; max-width: 72rem; margin: 0 auto; padding: 1.5rem; }
nav { font-size: 0.9rem; margin-bottom: 1.5rem; }
a { color: #0550ae; }
h1, h2, h3 { line-height: 1.25; }
h1 { border-bottom: 1px solid #d0d7de; padding-bottom: 0.3rem; }
code { font: 0.875em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: #f6f8fa; padding: 0.1em 0.3em; border-radius: 4px; overflow-wrap: anywhere; }
pre { background: #f6f8fa; padding: 0.8rem; overflow-x: auto; border-radius: 6px; }
pre code { padding: 0; background: none; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; margin: 1rem 0; font-size: 0.9rem; }
th, td { border: 1px solid #d0d7de; padding: 0.35rem 0.6rem; vertical-align: top; }
th { background: #f6f8fa; }
blockquote { margin: 0; padding: 0 1rem; color: #59636e; border-left: 0.25rem solid #d0d7de; }
footer { margin-top: 2.5rem; font-size: 0.85rem; color: #59636e; }
""".strip()

_SAFE_URL = re.compile(r"^(https?://|mailto:|#|[^:]*$)", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_UNORDERED = re.compile(r"^\s*[-*+]\s+(.*)$")
_TABLE_DIVIDER = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")


def _emphasis(text: str) -> str:
    """Bold and italic on text that is already escaped."""
    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", text)


def _links(text: str) -> str:
    """Links in raw text, escaped piecewise. Unsafe targets keep only their label."""
    out: list[str] = []
    last = 0
    for match in re.finditer(r"\[([^\]]+)\]\(([^)\s]+)\)", text):
        out.append(_emphasis(html.escape(text[last : match.start()])))
        label = _emphasis(html.escape(match.group(1)))
        url = match.group(2)
        if _SAFE_URL.match(url):
            out.append(f'<a href="{html.escape(url, quote=True)}">{label}</a>')
        else:
            out.append(label)
        last = match.end()
    out.append(_emphasis(html.escape(text[last:])))
    return "".join(out)


def inline(text: str) -> str:
    """Render one line of inline Markdown. Code spans are escaped and never formatted."""
    parts = re.split(r"(`+)(.+?)\1", text)
    out: list[str] = []
    # re.split with two groups yields: text, fence, code, text, fence, code, ...
    for index in range(0, len(parts), 3):
        out.append(_links(parts[index]))
        if index + 2 < len(parts):
            out.append(f"<code>{html.escape(parts[index + 2].strip())}</code>")
    return "".join(out)


def _cells(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", row)]


def _alignments(divider: str) -> list[str | None]:
    result: list[str | None] = []
    for cell in _cells(divider):
        if cell.startswith(":") and cell.endswith(":"):
            result.append("center")
        elif cell.endswith(":"):
            result.append("right")
        elif cell.startswith(":"):
            result.append("left")
        else:
            result.append(None)
    return result


def _table(header: str, divider: str, rows: list[str]) -> str:
    aligns = _alignments(divider)

    def cell(tag: str, text: str, index: int) -> str:
        align = aligns[index] if index < len(aligns) else None
        attr = f' style="text-align: {align}"' if align else ""
        return f"<{tag}{attr}>{inline(text)}</{tag}>"

    head = "".join(cell("th", text, i) for i, text in enumerate(_cells(header)))
    body = "\n".join(
        "<tr>" + "".join(cell("td", text, i) for i, text in enumerate(_cells(row))) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table>\n'
        f"<thead><tr>{head}</tr></thead>\n<tbody>\n{body}\n</tbody>\n</table></div>"
    )


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        not line.strip()
        or line.lstrip().startswith("```")
        or _HEADING.match(line)
        or _RULE.match(line)
        or _UNORDERED.match(line)
        or _ORDERED.match(line)
        or line.lstrip().startswith(">")
        or (line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_DIVIDER.match(lines[i + 1]))
    )


def render_markdown(text: str) -> str:
    """Render the Markdown subset the committed reports use into escaped HTML."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            language = stripped[3:].strip().split(" ")[0]
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # the closing fence, or the end of an unclosed block
            cls = f' class="language-{html.escape(language, quote=True)}"' if language else ""
            blocks.append(f"<pre><code{cls}>{html.escape(chr(10).join(code))}</code></pre>")
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        if _RULE.match(line):
            blocks.append("<hr>")
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and _TABLE_DIVIDER.match(lines[i + 1]):
            header, divider = line, lines[i + 1]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(_table(header, divider, rows))
            continue
        if stripped.startswith(">"):
            quoted = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quoted.append(lines[i].strip()[1:].lstrip())
                i += 1
            blocks.append(f"<blockquote>\n{render_markdown(chr(10).join(quoted))}\n</blockquote>")
            continue
        for pattern, tag in ((_UNORDERED, "ul"), (_ORDERED, "ol")):
            if pattern.match(line):
                items: list[str] = []
                while i < len(lines) and pattern.match(lines[i]):
                    items.append(pattern.match(lines[i]).group(1))
                    i += 1
                    # A wrapped item continues on indented lines that start no new block.
                    while i < len(lines) and lines[i].startswith((" ", "\t")) and not _starts_block(lines, i):
                        items[-1] += " " + lines[i].strip()
                        i += 1
                body = "\n".join(f"<li>{inline(item)}</li>" for item in items)
                blocks.append(f"<{tag}>\n{body}\n</{tag}>")
                break
        else:
            paragraph = [stripped]
            i += 1
            while i < len(lines) and not _starts_block(lines, i):
                paragraph.append(lines[i].strip())
                i += 1
            blocks.append(f"<p>{inline(' '.join(paragraph))}</p>")
    return "\n".join(blocks)


def _document(title: str, body: str, *, source: str | None = None) -> str:
    nav = '<nav><a href="index.html">All reports</a></nav>\n' if source else ""
    origin = (
        f'Rendered from <a href="{REPOSITORY_URL}/blob/main/{html.escape(source, quote=True)}">'
        f"<code>{html.escape(source)}</code></a>. "
        if source
        else ""
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)} · {SITE_TITLE}</title>\n"
        f"<style>\n{STYLE}\n</style>\n</head>\n<body>\n{nav}<main>\n{body}\n</main>\n"
        f"<footer>{origin}Synthetic contracts only; generated by "
        f'<a href="{REPOSITORY_URL}">{SITE_TITLE}</a>.</footer>\n'
        "</body>\n</html>\n"
    )


def _index() -> str:
    items = "\n".join(
        f'<li><a href="{html.escape(page.output, quote=True)}">{html.escape(page.title)}</a>'
        f" — {html.escape(page.summary)}</li>"
        for page in (*PAGES, *COPIED)
    )
    body = (
        f"<h1>{SITE_TITLE}</h1>\n"
        "<p>A deterministic, offline harness that scores AI contract reviews against "
        "hand-authored answer sets. These pages are rendered from the evidence committed "
        "in the repository, which CI regenerates and verifies on every change.</p>\n"
        f"<ul>\n{items}\n</ul>\n"
        f'<p>Source, tests and the release policy: <a href="{REPOSITORY_URL}">{REPOSITORY_URL}</a>.</p>'
    )
    return _document(SITE_TITLE, body)


def build(out: Path, root: Path = ROOT) -> list[Path]:
    """Write the site under `out` and return the files written, index first."""
    out.mkdir(parents=True, exist_ok=True)
    written = [out / "index.html"]
    written[0].write_text(_index(), encoding="utf-8")
    for page in PAGES:
        markdown = (root / page.source).read_text(encoding="utf-8")
        target = out / page.output
        target.write_text(_document(page.title, render_markdown(markdown), source=page.source), encoding="utf-8")
        written.append(target)
    for page in COPIED:
        target = out / page.output
        shutil.copyfile(root / page.source, target)
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory to write the site into")
    args = parser.parse_args(argv)
    for path in build(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
