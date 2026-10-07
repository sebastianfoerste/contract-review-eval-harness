"""Keep an improvement loop honest about which results it has already looked at.

Iterating on a matter means changing what the system is given, scoring, and changing
it again. That is sound on the development split. On the evaluation split it is
selection: once a configuration has been scored there, a different configuration
scored there was chosen with that result in view, and its number no longer describes
unseen issues.

This module records every scored run and says when that has happened. It does not
prevent the run. It labels it, so the report cannot present a tuned number as held out.

A configuration is everything that determines the output: the prompt as sent, which
contains the documents shown, plus the model and the reasoning effort. An output file
of unknown origin is its own configuration, identified by its content.

The guard has limits it does not hide. It judges one round and one condition id at a
time. A tuned prompt registered under a new condition id, or tuning on one round
before scoring the next, is not detected here; both are changes to the manifest and
visible in version control.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

EXPERIMENTS_DIR = Path("experiments")
LOG_SCHEMA = "contract-review-eval.matter-experiment-log.v1"


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def configuration_id(
    *,
    matter_id: str,
    round_id: str,
    condition_id: str,
    prompt_sha256: str | None,
    model: str | None,
    effort: str | None,
    output_sha256: str | None = None,
) -> str:
    """Identity of what produced an output.

    `prompt_sha256` is the hash of the prompt as sent. A live run and the later
    scoring of its capture therefore share one id. `output_sha256` is given only for
    an output file that records no prompt, where the content is all there is to go on.
    """
    return _digest({
        "matter_id": matter_id,
        "round_id": round_id,
        "condition_id": condition_id,
        "prompt_sha256": prompt_sha256,
        "model": model,
        "effort": effort,
        "output_sha256": output_sha256,
    })


def default_log_path(matter_id: str, root: Path = Path(".")) -> Path:
    return root / EXPERIMENTS_DIR / matter_id / "log.jsonl"


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def eval_guard(
    entries: list[dict[str, Any]],
    *,
    matter_id: str,
    round_id: str,
    condition_id: str,
    configuration: str,
    gold_sha256: str | None = None,
) -> dict[str, Any]:
    """Has the evaluation split of this round already been looked at in a way that taints this run?

    Two things taint it. A different configuration of the same condition was scored
    there before, so this one was chosen with that result in view. Or the answers
    changed after any condition was scored there, which is how an inconvenient issue
    gets moved to the development split.

    Conditions are otherwise judged separately. Comparing the baseline with the
    matter condition on the evaluation split is the experiment itself.
    """
    in_round = [
        e for e in entries
        if e.get("matter_id") == matter_id
        and e.get("round_id") == round_id
        and e.get("split") in ("eval", "all")
    ]
    prior = [e for e in in_round if e.get("condition_id") == condition_id]
    others = sorted({e.get("configuration_id") for e in prior} - {configuration, None})
    answers_changed = gold_sha256 is not None and any(
        e.get("gold_sha256") not in (None, gold_sha256) for e in in_round
    )

    notes = []
    if others:
        notes.append(
            "The evaluation split of this round was scored earlier under a different "
            "configuration of this condition. This result was produced after that one "
            "was visible, so it is not a held-out measurement."
        )
    if answers_changed:
        notes.append(
            "The answers for this round changed after its evaluation split had been "
            "scored, so this result is not comparable with the earlier one and is not "
            "a held-out measurement."
        )
    return {
        "prior_eval_runs": len(prior),
        "contaminated": bool(notes),
        "other_configurations": others,
        "answers_changed": answers_changed,
        "note": " ".join(notes) or None,
    }


def append_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": LOG_SCHEMA,
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
        **entry,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
