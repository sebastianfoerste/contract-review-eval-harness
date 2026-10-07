"""What a reviewing lawyer did with a matter review, recorded per finding.

Scores against a gold set say whether a review found what the answer key expects.
They cannot say whether a lawyer would use it. That is measured here, by a person:
for each finding, whether they accepted, corrected or rejected it, how useful it was,
why, and how long the whole review took.

Three rules keep the record from claiming more than it holds.

- A session is bound to the hash of the exact output reviewed. Ratings cannot migrate
  to a later, better output.
- The template shown to the reviewer does not name the condition that produced the
  output. The condition is recovered from the hash afterwards.
- Every session declares what kind of evidence it is. Only sessions by practising
  lawyers other than the author count toward a pilot summary.
"""

from __future__ import annotations

import json
import re
import statistics
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contract_eval.matter import MatterReview

SESSION_SCHEMA = "contract-review-eval.reviewer-session.v1"

USEFULNESS_RUBRIC: dict[int, str] = {
    4: "Usable as written. I would send it on with my name under it.",
    3: "Useful after correction. The point is right; wording, severity or action needed fixing.",
    2: "Not useful. Correct or harmless, but it told me nothing I needed.",
    1: "Misleading. Wrong in a way that would have cost time or caused harm if relied on.",
}

EvidenceClass = Literal["practising_lawyer", "author_self_review", "synthetic_example"]
_PSEUDONYM = re.compile(r"^R[0-9]{2,}$")


class FindingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    decision: Literal["accepted", "corrected", "rejected"]
    usefulness: int = Field(ge=1, le=4)
    reason: str = ""

    @model_validator(mode="after")
    def validate_decision(self) -> "FindingDecision":
        # An acceptance needs no explanation. A correction or rejection without one
        # is the half of the record that could have changed the system.
        if self.decision != "accepted" and not self.reason.strip():
            raise ValueError(
                f"{self.finding_id}: a {self.decision} finding needs a written reason"
            )
        return self


class ReviewerSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["contract-review-eval.reviewer-session.v1"] = Field(
        default=SESSION_SCHEMA, alias="schema"
    )
    matter_id: str
    round_id: str
    review_sha256: str
    # A pseudonym such as R01. A public repository is a permanent, searchable record,
    # so a reviewer is named only in a place they have agreed to.
    reviewer_id: str
    reviewer_profile: str = ""
    evidence_class: EvidenceClass
    minutes_to_reviewable_draft: float | None = Field(default=None, ge=0)
    review_minutes: float = Field(gt=0)
    decisions: list[FindingDecision] = Field(min_length=1)
    material_omissions: list[str] = Field(default_factory=list)
    workflow_feedback: str = ""

    @model_validator(mode="after")
    def validate_session(self) -> "ReviewerSession":
        if not _PSEUDONYM.match(self.reviewer_id):
            raise ValueError(
                f"reviewer_id {self.reviewer_id!r} must be a pseudonym of the form R01"
            )
        ids = [d.finding_id for d in self.decisions]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"duplicate decisions for findings: {repeated}")
        return self


def blank_session(matter_id: str, round_id: str, review: MatterReview) -> dict[str, Any]:
    """A session for a reviewer to fill in. It names the output by hash only."""
    finding_ids = [
        f.finding_id for f in (*review.conflicts, *review.positions, *review.escalations)
    ]
    return {
        "schema": SESSION_SCHEMA,
        "matter_id": matter_id,
        "round_id": round_id,
        "review_sha256": review.canonical_sha256(),
        "reviewer_id": "",
        "reviewer_profile": "",
        "evidence_class": "",
        "minutes_to_reviewable_draft": None,
        "review_minutes": None,
        "decisions": [
            {"finding_id": finding_id, "decision": "", "usefulness": None, "reason": ""}
            for finding_id in finding_ids
        ],
        "material_omissions": [],
        "workflow_feedback": "",
    }


def validate_against_review(session: ReviewerSession, review: MatterReview) -> None:
    """A session must rate exactly the findings of the output it is bound to."""
    if session.review_sha256 != review.canonical_sha256():
        raise ValueError("session is bound to a different review output")
    expected = {
        f.finding_id for f in (*review.conflicts, *review.positions, *review.escalations)
    }
    rated = {d.finding_id for d in session.decisions}
    if rated != expected:
        raise ValueError(
            f"session must rate every finding once; missing={sorted(expected - rated)} "
            f"unknown={sorted(rated - expected)}"
        )


def load_sessions(directory: Path) -> list[ReviewerSession]:
    if not directory.is_dir():
        return []
    return [
        ReviewerSession.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]


def summarise_sessions(sessions: list[ReviewerSession]) -> dict[str, Any]:
    """Aggregate sessions that count as pilot evidence, and count the ones that do not."""
    counted = [s for s in sessions if s.evidence_class == "practising_lawyer"]
    excluded = len(sessions) - len(counted)
    if not counted:
        return {
            "measured": False,
            "reason": (
                "no session by a practising lawyer other than the author is recorded"
            ),
            "sessions_excluded": excluded,
        }

    decisions = [d for s in counted for d in s.decisions]
    total = len(decisions)
    drafts = [
        s.minutes_to_reviewable_draft for s in counted
        if s.minutes_to_reviewable_draft is not None
    ]
    return {
        "measured": True,
        "sessions": len(counted),
        "reviewers": len({s.reviewer_id for s in counted}),
        "sessions_excluded": excluded,
        "findings_rated": total,
        "accepted_rate": sum(d.decision == "accepted" for d in decisions) / total,
        "corrected_rate": sum(d.decision == "corrected" for d in decisions) / total,
        "rejected_rate": sum(d.decision == "rejected" for d in decisions) / total,
        "mean_usefulness": statistics.fmean(d.usefulness for d in decisions),
        "median_review_minutes": statistics.median(s.review_minutes for s in counted),
        "median_minutes_to_reviewable_draft": statistics.median(drafts) if drafts else None,
        "material_omissions": sum(len(s.material_omissions) for s in counted),
    }
