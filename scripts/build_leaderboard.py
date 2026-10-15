"""Build the leaderboard from committed review outputs, so no figure is typed by hand.

Every row is re-scored through the production scorer with declared aliases on, the
release policy's mode, and decided by the release policy. A leaderboard that copied
numbers out of old reports could drift from the scorer it claims to rank by.

    python scripts/build_leaderboard.py           # write examples/leaderboard.{md,json}
    python scripts/build_leaderboard.py --check   # exit 1 if the committed files drifted

Sources, read from the checkout:

    fixtures/<case>_stub.json        the deterministic stub, a labelled baseline row
    examples/raw-output/             raw adapter output, pinned by MANIFEST.json
    examples/captures/*.json         captures; one already in the manifest joins its row

Nothing here records when it ran, so the same inputs produce the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval import ReviewOutput, Verdict, evaluate_review, load_case  # noqa: E402
from contract_eval.cases import ALL_CASES  # noqa: E402
from contract_eval.capture import canonical_sha256, read_capture  # noqa: E402
from contract_eval.release_certificate import POLICY_ID  # noqa: E402
from contract_eval.replay import verify_capture  # noqa: E402

SCHEMA = "contract-review-eval.leaderboard.v1"
OUTPUT_JSON = "examples/leaderboard.json"
OUTPUT_MARKDOWN = "examples/leaderboard.md"
OUTPUTS: tuple[str, ...] = (OUTPUT_MARKDOWN, OUTPUT_JSON)
RAW_OUTPUT_DIR = "examples/raw-output"
CAPTURE_DIR = "examples/captures"
ALIAS_MODE = "on"
STUB_LABEL = "stub adapter (deterministic baseline)"

# Worst first, so a row's verdict is the first of these any of its cases reached.
VERDICT_ORDER: tuple[Verdict, ...] = (
    Verdict.REJECT,
    Verdict.HUMAN_REVIEW_REQUIRED,
    Verdict.PILOT_ELIGIBLE,
)

# Mean across a row's cases. Hallucinations are summed instead: one fabricated quote
# is one too many, and averaging would hide it behind the cases that had none.
MEAN_METRICS: tuple[str, ...] = (
    "clause_f1",
    "span_coverage",
    "risk_f1",
    "risk_severity_accuracy",
    "citation_grounding",
)


class LeaderboardError(RuntimeError):
    """A source cannot be trusted, so no row is built from it."""


def harness_version(root: Path = ROOT) -> str:
    """The version of the scorer that produced the numbers, read from the checkout."""
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _score_case(case: str, review: ReviewOutput, origin: dict[str, Any], root: Path) -> dict[str, Any]:
    """One case's scores and decision, through `evaluate_review` and nothing else."""
    result = evaluate_review(review, load_case(case, root=root), alias_mode=ALIAS_MODE)
    return {
        "case": case,
        "decision": str(result.verdict),
        "blockers": list(result.blockers),
        "review_items": list(result.review_items),
        "review_sha256": result.review_sha256,
        "origin": origin,
        "scores": {name: result.scores[name] for name in (*MEAN_METRICS, "hallucination_count")},
    }


def _row(
    *,
    tool: str,
    kind: str,
    date: str | None,
    version: str,
    cases: list[dict[str, Any]],
    cost_usd: float | None = None,
    latency_ms: float | None = None,
) -> dict[str, Any]:
    cases = sorted(cases, key=lambda item: item["case"])
    decisions = {item["decision"] for item in cases}
    verdict = next(str(v) for v in VERDICT_ORDER if str(v) in decisions)
    metrics: dict[str, Any] = {
        name: sum(item["scores"][name] for item in cases) / len(cases) for name in MEAN_METRICS
    }
    metrics["hallucination_count"] = sum(item["scores"]["hallucination_count"] for item in cases)
    return {
        "tool": tool,
        "kind": kind,
        "date": date,
        "harness_version": version,
        "cases": [item["case"] for item in cases],
        "metrics": metrics,
        # No committed capture records spend or wall-clock time. A null says so; a
        # zero would claim the run was free and instant.
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "verdict": verdict,
        "per_case": cases,
    }


def _stub_row(root: Path, version: str) -> dict[str, Any]:
    cases = []
    for case in ALL_CASES:
        path = root / "fixtures" / f"{case}_stub.json"
        data = path.read_bytes()
        review = ReviewOutput.model_validate_json(data)
        origin = {"path": path.relative_to(root).as_posix(), "sha256": _sha256(data)}
        cases.append(_score_case(case, review, origin, root))
    return _row(tool=STUB_LABEL, kind="baseline", date=None, version=version, cases=cases)


def _manifest_rows(root: Path, version: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Rows for the raw-output manifest, and each case keyed by its output digest.

    A file whose bytes no longer match the manifest is refused rather than scored:
    the manifest is what makes a raw output evidence instead of an anonymous file.
    """
    manifest_path = root / RAW_OUTPUT_DIR / "MANIFEST.json"
    if not manifest_path.is_file():
        return [], {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = manifest["model"]
    date = manifest["output_generated_at"][:10]
    by_digest: dict[str, dict[str, Any]] = {}
    cases = []
    for case, expected_sha in sorted(manifest["sha256"].items()):
        path = root / RAW_OUTPUT_DIR / f"{case}-{model}-{date}.json"
        data = path.read_bytes()
        if _sha256(data) != expected_sha:
            raise LeaderboardError(f"{path.relative_to(root).as_posix()}: sha256 differs from MANIFEST.json")
        review = ReviewOutput.model_validate_json(data)
        origin = {"path": path.relative_to(root).as_posix(), "sha256": expected_sha, "capture_ids": []}
        entry = _score_case(case, review, origin, root)
        by_digest[expected_sha] = entry
        cases.append(entry)
    row = _row(tool=model, kind="captured", date=date, version=version, cases=cases)
    return [row], by_digest


def _capture_rows(root: Path, version: str, known: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for captures that are not already a manifest entry, one per run.

    The committed captures are the manifest's outputs imported as captures. Scoring
    them again as a second row would count one generation twice, so a capture whose
    raw bytes match a manifest digest only adds its id to that case.
    """
    runs: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for path in sorted((root / CAPTURE_DIR).glob("*.json")):
        capture = read_capture(path)
        verification = verify_capture(capture, root=root)
        if not verification["authentic"]:
            raise LeaderboardError(
                f"{path.relative_to(root).as_posix()}: " + ", ".join(verification["errors"])
            )
        if not verification["scoreable"]:
            continue
        digest = capture.response.raw_text_sha256 if capture.response else None
        if digest in known:
            known[digest]["origin"]["capture_ids"].append(capture.capture_id)
            continue
        model = (
            (capture.request.model if capture.request else None)
            or (capture.response.returned_model if capture.response else None)
            or capture.adapter_id
        )
        date = (capture.completed_at or capture.started_at or "")[:10] or None
        origin = {
            "path": path.relative_to(root).as_posix(),
            "capture_id": capture.capture_id,
            "capture_sha256": capture.integrity_sha256,
            "latency_seconds": capture.latency_seconds,
            "cost_usd": capture.cost.estimated_cost if capture.cost else None,
        }
        runs.setdefault((model, date or "", capture.run_id), []).append(
            _score_case(capture.case, capture.output, origin, root)
        )
    rows = []
    for (model, date, _run), cases in sorted(runs.items()):
        cost_usd, latency_ms = _measurements(cases)
        rows.append(_row(
            tool=model, kind="captured", date=date or None, version=version, cases=cases,
            cost_usd=cost_usd, latency_ms=latency_ms,
        ))
    return rows


def _measurements(cases: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """A run's total cost and mean latency per case, or None unless every case has one.

    A partial sum would understate what the run cost, and a mean over the cases that
    happened to be timed would describe a different run.
    """
    costs = [case["origin"].get("cost_usd") for case in cases]
    latencies = [case["origin"].get("latency_seconds") for case in cases]
    cost = None if None in costs else round(sum(costs), 8)
    latency = None if None in latencies else round(1000 * sum(latencies) / len(latencies), 1)
    return cost, latency


def _sort_key(row: dict[str, Any]) -> tuple:
    """Best verdict first, then clause F1; the identity fields make the order total."""
    return (
        -VERDICT_ORDER.index(Verdict(row["verdict"])),
        -row["metrics"]["clause_f1"],
        row["tool"],
        row["date"] or "",
        row["harness_version"],
    )


def build(root: Path = ROOT) -> dict[str, Any]:
    """The leaderboard payload, computed from the sources under `root`."""
    version = harness_version(root)
    manifest_rows, known = _manifest_rows(root, version)
    rows = [_stub_row(root, version), *manifest_rows, *_capture_rows(root, version, known)]
    payload = {
        "schema": SCHEMA,
        "policy": POLICY_ID,
        "alias_mode": ALIAS_MODE,
        "rows": sorted(rows, key=_sort_key),
    }
    return {**payload, "leaderboard_sha256": canonical_sha256(payload)}


def _fmt(value: float | int | None, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{value:.{digits}f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Contract review leaderboard",
        "",
        "**Generated from committed review outputs. Do not edit by hand.**",
        "",
        f"Regenerate with `make leaderboard`. Leaderboard digest: `{payload['leaderboard_sha256']}`.",
        "",
        f"- Release policy: `{payload['policy']}`",
        f"- Declared clause aliases: {payload['alias_mode']}",
        "- Date is when the output was produced. Harness is the scorer version that",
        "  computed the row, the same for every row; it is not the version that produced the output.",
        "- Scores are means across a row's cases; hallucinations are summed.",
        "- Verdict is the worst case decision; per-case decisions are in `leaderboard.json`.",
        "- Cost is the run's total across its cases and latency the mean per case; both",
        "  read n/a unless every capture in the row records them.",
        "- Synthetic contracts only. A verdict here ranks committed outputs for comparison;",
        "  it is not a release certificate and establishes no fitness for contract review.",
        "",
        "| Rank | Tool / model | Kind | Date | Harness | Clause F1 | Span coverage | Risk F1 "
        "| Severity accuracy | Citation grounding | Hallucinations | Cost (USD) | Latency (ms) | Verdict |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for rank, row in enumerate(payload["rows"], start=1):
        m = row["metrics"]
        lines.append(
            f"| {rank} | {row['tool']} | {row['kind']} | {row['date'] or 'n/a'} "
            f"| {row['harness_version']} | {_fmt(m['clause_f1'])} | {_fmt(m['span_coverage'])} "
            f"| {_fmt(m['risk_f1'])} | {_fmt(m['risk_severity_accuracy'])} "
            f"| {_fmt(m['citation_grounding'])} | {m['hallucination_count']} "
            f"| {_fmt(row['cost_usd'], 4)} | {_fmt(row['latency_ms'], 0)} | {row['verdict']} |"
        )
    lines += ["", "## Per-case decisions", ""]
    lines += ["| Tool / model | Date | Case | Decision | Blockers | Review items |", "|---|---|---|---|---:|---:|"]
    for row in payload["rows"]:
        for item in row["per_case"]:
            lines.append(
                f"| {row['tool']} | {row['date'] or 'n/a'} | {item['case']} | {item['decision']} "
                f"| {len(item['blockers'])} | {len(item['review_items'])} |"
            )
    return "\n".join(lines) + "\n"


def render_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def write(out_root: Path, root: Path = ROOT) -> list[Path]:
    payload = build(root)
    written = []
    for rel, text in ((OUTPUT_MARKDOWN, render_markdown(payload)), (OUTPUT_JSON, render_json(payload))):
        target = out_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def check(out_root: Path, root: Path = ROOT) -> list[str]:
    """Where the files under `out_root` differ from a fresh build; empty when none do."""
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        write(staging, root)
        drifted = []
        for rel in OUTPUTS:
            committed = out_root / rel
            if not committed.is_file():
                drifted.append(f"{rel}: missing")
            elif committed.read_bytes() != (staging / rel).read_bytes():
                drifted.append(f"{rel}: differs from generated output")
    return drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed files drifted")
    parser.add_argument("--out", type=Path, default=ROOT, help="root the examples/ files live under")
    args = parser.parse_args(argv)

    if args.check:
        drifted = check(args.out)
        if drifted:
            print("\n".join(drifted))
            print("run `make leaderboard` and commit the result")
            return 1
        print(f"leaderboard check passed: {len(OUTPUTS)} artifacts reproduce byte-for-byte")
        return 0
    for path in write(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
