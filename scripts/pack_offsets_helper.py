#!/usr/bin/env python3
"""Find the character offsets of a quote you have copied out of a contract.

The annotation format locates every obligation by raw character offsets rather than by
clause number, because clause numbers move when a document is renumbered and offsets do
not. Counting them by hand is miserable and error-prone, so this does it for you.

    python3 offsets.py nda "Recipient shall not disclose"
    python3 offsets.py nda          reads quotes from stdin, one per line

It prints start and end such that source[start:end] is exactly your quote. Copying out
of a rendered view often changes the whitespace, so a quote that does not match exactly
is retried with runs of whitespace treated as equivalent, and the offsets still come
back pointing into the file as delivered.

It refuses to guess. A quote that appears twice is reported as ambiguous rather than
resolved to the first hit, because the wrong span silently scores as a different duty.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = ("nda", "saas", "dpa")


def load(case: str) -> str:
    path = HERE / "contracts" / f"{case}_sample.md"
    if not path.exists():
        sys.exit(f"unknown case {case!r}; expected one of {', '.join(CASES)}")
    return path.read_text(encoding="utf-8")


def normalized_index(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace, remembering where each surviving character came from."""
    out: list[str] = []
    origin: list[int] = []
    previous_was_space = False
    for position, character in enumerate(text):
        if character.isspace():
            if previous_was_space or not out:
                continue
            out.append(" ")
            origin.append(position)
            previous_was_space = True
        else:
            out.append(character)
            origin.append(position)
            previous_was_space = False
    return "".join(out), origin


def find(source: str, quote: str) -> tuple[int, int]:
    quote = quote.strip()
    if not quote:
        raise ValueError("empty quote")

    hits = []
    start = source.find(quote)
    while start != -1:
        hits.append((start, start + len(quote)))
        start = source.find(quote, start + 1)
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ValueError(f"appears {len(hits)} times; quote more surrounding text")

    # Whitespace-insensitive retry, reported back in raw offsets.
    flat_source, origin = normalized_index(source)
    flat_quote, _ = normalized_index(quote)
    hits = []
    start = flat_source.find(flat_quote)
    while start != -1:
        hits.append(start)
        start = flat_source.find(flat_quote, start + 1)
    if not hits:
        raise ValueError("not found; copy the text directly from the contract file")
    if len(hits) > 1:
        raise ValueError(f"appears {len(hits)} times; quote more surrounding text")
    begin = origin[hits[0]]
    last = origin[hits[0] + len(flat_quote) - 1]
    return begin, last + 1


def report(source: str, quote: str) -> None:
    try:
        start, end = find(source, quote)
    except ValueError as error:
        print(f"  no offsets: {error}", file=sys.stderr)
        return
    print(json.dumps({"start": start, "end": end, "quote": source[start:end]},
                     ensure_ascii=False))


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    source = load(argv[1])
    if len(argv) > 2:
        report(source, " ".join(argv[2:]))
        return 0
    for line in sys.stdin:
        if line.strip():
            report(source, line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
