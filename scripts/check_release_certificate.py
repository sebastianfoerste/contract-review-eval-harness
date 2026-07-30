"""Fail when the committed release certificate differs from a deterministic rebuild."""

import json
from pathlib import Path

from contract_eval.cli import evaluate_case
from contract_eval.release_certificate import verify_release_certificate

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    scores = {case: evaluate_case(case, live=False) for case in ("nda", "saas")}
    path = ROOT / "examples" / "release-certificate.json"
    if not path.is_file():
        print("missing committed artifact: examples/release-certificate.json")
        return 1
    actual = json.loads(path.read_text(encoding="utf-8"))
    verification = verify_release_certificate(actual, scores, root=ROOT)
    if verification["status"] != "VALID":
        print(
            "release certificate verification failed: "
            + ", ".join(verification["errors"])
        )
        print("run `make certificate` and commit the result")
        return 1
    print(
        "release-certificate check passed: "
        f"{verification['verification_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
