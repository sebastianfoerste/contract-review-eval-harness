"""Fail when the committed live-run report differs from a fresh generation.

The report is evidence. If it can drift from the captures it claims to summarise,
it is a claim rather than a derivation.
"""

import filecmp
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from generate_live_run_report import SPEC, build  # noqa: E402


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    targets = [spec["outputs"]["markdown"], spec["outputs"]["json"]]

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        for rel in targets:
            (staging / rel).parent.mkdir(parents=True, exist_ok=True)
        build(staging)

        drifted = []
        for rel in targets:
            committed = ROOT / rel
            if not committed.is_file():
                drifted.append(f"{rel}: missing")
            elif not filecmp.cmp(committed, staging / rel, shallow=False):
                drifted.append(f"{rel}: differs from generated output")

    if drifted:
        print("\n".join(drifted))
        print("run `make live-run-report` and commit the result")
        return 1
    print(f"live-run report check passed: {len(targets)} artifacts reproduce byte-for-byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
