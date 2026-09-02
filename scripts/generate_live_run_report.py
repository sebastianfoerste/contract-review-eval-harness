"""Generate the live-run report from captures, so no figure is transcribed by hand.

The previous report was typed from terminal output. One of its tables compared two
different generations while claiming they were one output scored twice. Generating
from captures removes the class of error rather than the instance.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from contract_eval.capture import canonical_sha256, read_capture  # noqa: E402
from contract_eval.replay import replay  # noqa: E402

SPEC = ROOT / "robustness" / "replay-spec.v1.json"


def build(out_root: Path) -> dict:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    modes = tuple(spec["alias_modes"])

    rows = []
    for entry in spec["captures"]:
        capture = read_capture(ROOT / entry["path"])
        result = replay(capture, alias_modes=modes, allow_input_drift=True, root=ROOT)
        for mode in modes:
            scores = result["scores"][mode]
            rows.append({
                "case": entry["case"],
                "aliases": mode,
                "clause_precision": scores["clause_precision"],
                "clause_recall": scores["clause_recall"],
                "clause_f1": scores["clause_f1"],
                "risk_precision": scores["risk_precision"],
                "risk_recall": scores["risk_recall"],
                "risk_severity_accuracy": scores["risk_severity_accuracy"],
                "span_coverage": scores["span_coverage"],
                "citation_grounding": scores["citation_grounding"],
                "citation_grounded": scores["citation_grounded"],
                "citation_total": scores["citation_total"],
                "hallucination_count": scores["hallucination_count"],
            })

    payload = {
        "schema": "contract-review-eval.live-run-report.v1",
        "spec_id": spec["spec_id"],
        "report_date": spec["report_date"],
        "model_label": spec["model_label"],
        "comparison_only": spec["comparison_only"],
        "disclosures": spec["disclosures"],
        "rows": rows,
    }
    payload["report_sha256"] = canonical_sha256(
        {k: v for k, v in payload.items() if k != "report_sha256"}
    )

    (out_root / spec["outputs"]["json"]).parent.mkdir(parents=True, exist_ok=True)
    (out_root / spec["outputs"]["json"]).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_root / spec["outputs"]["markdown"]).write_text(render(payload), encoding="utf-8")
    return payload


def render(payload: dict) -> str:
    lines = [
        f"# Live model run, {payload['report_date']}",
        "",
        "**Generated from captured output. Do not edit by hand.**",
        "",
        f"Regenerate with `make live-run-report`. Report digest: `{payload['report_sha256']}`.",
        "",
        f"- Model label: `{payload['model_label']}`",
        f"- Comparison only: {str(payload['comparison_only']).lower()}",
        "",
        "## Disclosures",
        "",
    ]
    lines += [f"- {d}" for d in payload["disclosures"]]
    lines += [
        "",
        "## One captured output, scored twice",
        "",
        "Each pair of rows below scores identical bytes. The only difference is whether",
        "declared clause synonyms were applied, so the delta isolates the scoring rule.",
        "",
        "| Case | Aliases | Clause P | Clause R | Clause F1 | Risk P | Risk R | Severity | Span coverage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['case']} | {row['aliases']} | {row['clause_precision']:.3f} "
            f"| {row['clause_recall']:.3f} | {row['clause_f1']:.3f} "
            f"| {row['risk_precision']:.2f} | {row['risk_recall']:.2f} "
            f"| {row['risk_severity_accuracy']:.2f} | {row['span_coverage']:.3f} |"
        )
    lines += [
        "",
        "## Citation grounding",
        "",
        "| Case | Grounded | Total | Unsupported |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in payload["rows"]:
        if row["aliases"] != payload["rows"][0]["aliases"]:
            continue
        lines.append(
            f"| {row['case']} | {row['citation_grounded']} | {row['citation_total']} "
            f"| {row['hallucination_count']} |"
        )
    lines += [
        "",
        "Grounding is an exact contiguous span of the normalised source.",
        "",
        "## Boundary",
        "",
        "Single run, single model, three synthetic agreements, one annotator, no blind",
        "adjudication. Nothing here authorises reliance on an AI contract review without",
        "a qualified lawyer confirming every flagged risk and every citation.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT
    result = build(target)
    print(f"generated live-run report: {result['report_sha256'][:16]} ({len(result['rows'])} rows)")
