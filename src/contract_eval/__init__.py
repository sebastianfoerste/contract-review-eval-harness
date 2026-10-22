"""contract_eval — measure the quality of AI contract review against an answer set.

    from contract_eval import evaluate_review, load_case

    result = evaluate_review("my-review.json", load_case("nda"))
    print(result.verdict, result.scores["citation_grounding"])
"""

from contract_eval.api import (
    Case,
    ReviewResult,
    Verdict,
    decide,
    evaluate_review,
    load_case,
    load_review,
    score_review,
)
from contract_eval.models import ExpectedAnswer, ReviewOutput

__all__ = [
    "Case",
    "ExpectedAnswer",
    "ReviewOutput",
    "ReviewResult",
    "Verdict",
    "decide",
    "evaluate_review",
    "load_case",
    "load_review",
    "score_review",
]
