"""Import the preserved 2026-09-01 raw outputs as legacy captures.

The originals stay where they are. They are the historical evidence; this only wraps
them in the envelope so replay can consume them. Provider metadata that was never
recorded is null rather than invented, and the origin says `legacy_file` so a reader
cannot mistake an import for a live capture.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.capture import (  # noqa: E402
    CapturedReview,
    ProviderResponse,
    snapshot_of,
    text_sha256,
    write_capture,
)
from contract_eval.models import ReviewOutput  # noqa: E402

RAW_DIR = ROOT / "examples" / "raw-output"
OUT_DIR = ROOT / "examples" / "captures"
MODEL = "claude-opus-5"
DATE = "2026-09-01"


def main() -> int:
    manifest = json.loads((RAW_DIR / "MANIFEST.json").read_text(encoding="utf-8"))
    recorded = manifest["sha256"]

    imported = []
    for case, expected_hash in sorted(recorded.items()):
        raw_path = RAW_DIR / f"{case}-{MODEL}-{DATE}.json"
        blob = raw_path.read_text(encoding="utf-8")
        actual = text_sha256(blob)
        if actual != expected_hash:
            print(f"{case}: manifest hash mismatch\n  recorded {expected_hash}\n  actual   {actual}")
            return 1

        output = ReviewOutput.model_validate_json(blob)
        capture = CapturedReview(
            capture_id=f"legacy-{case}-{DATE}",
            run_id=f"legacy-{DATE}",
            origin="legacy_file",
            state="completed",
            case=case,
            started_at=f"{DATE}T00:00:00.000+00:00",
            completed_at=f"{DATE}T00:00:00.000+00:00",
            adapter_id="live",
            prompt_version="contract-review.prompt.v1",
            parser_version="contract-review.parser.v1",
            source=snapshot_of(Path("data") / f"{case}_sample.md", root=ROOT),
            gold=snapshot_of(Path("expected") / f"{case}.json", root=ROOT),
            # The original run did not preserve the request, request id, stop reason
            # or token usage. Those stay null; inventing them would fabricate
            # provenance for a historical artifact.
            request=None,
            response=ProviderResponse(
                raw_text=blob,
                raw_text_sha256=actual,
                returned_model=None,
                request_id=None,
                stop_reason=None,
            ),
            output=output,
            output_sha256=text_sha256(output.model_dump_json()),
        )
        path = write_capture(capture, OUT_DIR / f"{capture.capture_id}.json")
        imported.append(path.relative_to(ROOT))
        print(f"{case}: imported -> {path.relative_to(ROOT)}")

    print(f"imported {len(imported)} legacy captures with incomplete provider provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
