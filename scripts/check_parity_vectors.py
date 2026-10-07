"""Fail when the committed web parity vectors differ from the current scorer output.

The web app lives in a separate repository, so harness CI cannot run its tests.
The committed vectors make a scorer change fail here until the file is regenerated,
and that diff is the signal to re-export the web app and retest its TypeScript port.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from contract_eval.web_export import PARITY_VECTORS_PATH, check_parity_vectors, write_parity_vectors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Regenerate the committed vectors instead of checking them")
    args = parser.parse_args()
    if args.write:
        write_parity_vectors(ROOT)
        print(f"Wrote {PARITY_VECTORS_PATH}")
        return 0
    try:
        check_parity_vectors(ROOT)
    except ValueError as exc:
        print(f"Parity vectors failed: {exc}", file=sys.stderr)
        print("If the scorer change is intended, run `make parity-vectors`, commit the diff, then run `make web-export`.", file=sys.stderr)
        return 1
    print("Parity vectors passed: committed vectors reproduce byte-for-byte from the current scorer")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
