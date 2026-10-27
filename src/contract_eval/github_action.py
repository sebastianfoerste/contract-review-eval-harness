"""The scoring step of the repository's GitHub Action (`action.yml`).

The action installs this package and runs `python -m contract_eval.github_action`. Its
inputs arrive as environment variables instead of being interpolated into a shell
script, so a file name cannot inject a command. Every review goes through the same
`score` as `contract-eval score`, so the job summary shows the numbers the CLI prints.

Exit status follows the CLI: 1 when a decision fails the gate, 2 when a review or
answer set cannot be read, otherwise 0.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from contract_eval.cli import ScoreInputError, score, score_exit_code
from contract_eval.scorecard import render_score

RANK = {"PILOT_ELIGIBLE": 0, "HUMAN_REVIEW_REQUIRED": 1, "REJECT": 2}


def review_files(patterns: str) -> list[Path]:
    """Whitespace-separated paths or globs (`**` recurses), deduplicated and sorted."""
    found: set[Path] = set()
    for pattern in patterns.split():
        found.update(Path(match) for match in glob.glob(pattern, recursive=True))
    return sorted(path for path in found if path.is_file())


def result_stem(review: Path) -> str:
    """A file name for one review's results that two reviews cannot share."""
    return re.sub(r"[^A-Za-z0-9._-]+", "__", review.with_suffix("").as_posix()).strip("._")


def _row(review: Path, result: dict[str, Any]) -> str:
    s = result["scores"]
    return (
        f"| `{review}` | {result['case']} | **{result['decision']}** | {s['clause_f1']:.2f} "
        f"| {s['risk_f1']:.2f} | {s['citation_grounding']:.2f} | {s['hallucination_count']} |"
    )


def summary(scored: list[tuple[Path, dict[str, Any]]], errors: list[str]) -> str:
    lines = [
        "## contract-eval",
        "",
        "| Review | Case | Decision | Clause F1 | Risk F1 | Citation grounding | Hallucinations |",
        "|---|---|---|---:|---:|---:|---:|",
        *(_row(review, result) for review, result in scored),
        "",
    ]
    if any(result["comparison_only"] for _, result in scored):
        lines += [
            "Scored against your own answer set: comparison only, not certifiable.",
            "",
        ]
    lines += [f"- Could not score {error}" for error in errors]
    for review, result in scored:
        lines += [
            f"<details><summary><code>{review}</code>: {result['decision']}</summary>",
            "",
            render_score(result),
            "</details>",
            "",
        ]
    return "\n".join(lines)


def run(env: Mapping[str, str]) -> int:
    reviews = review_files(env.get("INPUT_REVIEWS", ""))
    if not reviews:
        print(f"::error::no review file matches {env.get('INPUT_REVIEWS', '')!r}")
        return 2
    case = env.get("INPUT_CASE") or None
    contract = env.get("INPUT_CONTRACT") or None
    gold = env.get("INPUT_GOLD") or None
    own = contract is not None or gold is not None
    if (case is not None and own) or (case is None and not (contract and gold)):
        print("::error::set either `case`, or both `contract` and `gold`")
        return 2
    alias_mode = env.get("INPUT_ALIASES") or "on"
    fail_on = env.get("INPUT_FAIL_ON") or "reject"
    if alias_mode not in ("on", "off") or fail_on not in ("reject", "human-review"):
        print("::error::`aliases` must be on or off; `fail-on` must be reject or human-review")
        return 2
    out = Path(env.get("INPUT_OUT") or "contract-eval-results")
    out.mkdir(parents=True, exist_ok=True)

    status = 0
    scored: list[tuple[Path, dict[str, Any]]] = []
    errors: list[str] = []
    for review in reviews:
        try:
            result = score(
                review,
                case=case,
                contract=Path(contract) if contract else None,
                gold=Path(gold) if gold else None,
                alias_mode=alias_mode,
            )
        except ScoreInputError as exc:
            reason = str(exc).splitlines()[0]
            print(f"::error file={review}::{reason}")
            errors.append(f"`{review}`: {reason}")
            status = max(status, 2)
            continue
        stem = result_stem(review)
        (out / f"{stem}.md").write_text(render_score(result), encoding="utf-8")
        (out / f"{stem}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        code = score_exit_code(result["decision"], fail_on)
        if code:
            reasons = ", ".join(result["blockers"] + result["review_items"])
            print(f"::error file={review}::{result['decision']}: {reasons}")
        else:
            print(f"{review}: {result['decision']}")
        status = max(status, code)
        scored.append((review, result))

    text = summary(scored, errors)
    summary_path = env.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    worst = max((result["decision"] for _, result in scored), key=RANK.__getitem__, default="")
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"decision={worst}\nresults-dir={out}\n")
    return status


if __name__ == "__main__":
    sys.exit(run(os.environ))
