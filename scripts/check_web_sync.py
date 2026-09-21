"""Check the complete web export, release version and real TypeScript parity tests."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from contract_eval.web_export import check_web_snapshot


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-dir", type=Path, default=Path(os.getenv("CONTRACT_EVAL_WEB_DIR", str(ROOT.parent / "contract-eval-web"))))
    parser.add_argument("--skip-node-test", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Compatibility flag; checks are always strict")
    args = parser.parse_args()
    try:
        check_web_snapshot(ROOT, args.web_dir)
        if not args.skip_node_test:
            subprocess.run(["npm", "test"], cwd=args.web_dir, check=True)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Web sync failed: {exc}", file=sys.stderr)
        return 1
    print("Web sync passed: complete dataset, reference evidence, release version and Python scoring parity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
