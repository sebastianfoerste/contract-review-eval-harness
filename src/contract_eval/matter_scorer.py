"""Score a matter review through the evidence it cites, document by document.

    citation (document_id, quote)
            |
            v
    found once in that document ........ grounded
    found only in another document ..... misattributed
    found more than once ............... ambiguous
    found nowhere ...................... unsupported
    document not shown to the system ... not_visible
            |
            v
    finding -> the one gold issue of its task whose evidence it quotes most of
            |
            v
    credit   1.0 for a position or escalation; decided by `conflict_credit` for a
             conflict, because a conflict has two sides and a finding may show one

Labels never enter the comparison. What a review calls an issue earns nothing; where
it quoted does.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Iterable

from contract_eval.matter import (
    MatterCitation,
    MatterGold,
    MatterIssue,
    MatterReview,
    Split,
)
from contract_eval.scorer import NormalizedIndex, build_normalized_index, normalize_text

UNBOUND_NO_EVIDENCE = "no_evidence"
UNBOUND_UNRESOLVED = "evidence_unresolved"
UNBOUND_AMBIGUOUS = "evidence_ambiguous"
UNBOUND_NO_ISSUE = "no_matching_issue"
ONE_SIDED = "one_sided_conflict_evidence"
RESTATED = "restated_earlier_round_issue"

# The share of a quotation that must lie inside an answer's passage for the quotation
# to count as pointing at it. Without a floor, quoting a whole document overlaps every
# passage in it and earns every issue anchored there.
MIN_QUOTE_FOCUS = 0.25

CreditRule = Callable[[frozenset[str], frozenset[str]], float]


def conflict_credit(
    cited_documents: frozenset[str], required_documents: frozenset[str]
) -> float:
    """How much of a conflict a finding has shown, from 0.0 to 1.0.

    `required_documents` are the documents the gold issue's evidence sits in.
    `cited_documents` are those among them in which the finding quoted that evidence.
    It is never empty: a finding that hit nothing is not bound to the issue at all.
    """
    # Strict rule: all required documents must be cited to earn credit.
    # Citing only some sides leaves the contradiction incomplete.
    return 1.0 if required_documents <= cited_documents else 0.0


@dataclass
class CitationResolution:
    citation_id: str
    document_id: str
    status: str  # grounded | misattributed | ambiguous | unsupported | not_visible
    span: tuple[int, int] | None = None
    found_in: list[str] = field(default_factory=list)


@dataclass
class FindingBinding:
    finding_id: str
    task: str
    issue_id: str | None = None
    credit: float = 0.0
    reason: str | None = None


@dataclass
class MatterScores:
    split: str
    issues_total: int
    # Issues on which some finding could earn credit from the documents this condition
    # was shown. The rest cannot be found by any system, so this is the condition's
    # ceiling. It is derived from the same rules that award credit: a position or an
    # escalation needs one of its passages visible, a conflict needs whatever the
    # credit rule needs.
    issues_answerable: int
    findings_total: int
    issue_recall: float | None
    finding_precision: float | None
    material_recall: float | None
    task_recall: dict[str, float | None]
    escalation_precision: float | None
    action_accuracy: float | None
    materiality_accuracy: float | None
    false_reassurance: list[str]
    conflicting_actions: list[str]
    missed_material: list[str]
    missed: list[str]
    unexpected_findings: list[str]
    restated_findings: list[str]
    unbound_findings: dict[str, str]
    duplicate_issue_findings: list[str]
    citations: dict[str, int]
    unreferenced_citations: int
    citation_grounding: float | None
    bindings: list[FindingBinding]


def find_whole(index: NormalizedIndex, needle: str) -> list[tuple[int, int]]:
    """Raw spans where `needle` occurs as whole words.

    A plain substring search would ground `nnex` in `Annex` and count `Section 4.1`
    twice in a document that also has `Section 4.12`.
    """
    if not needle:
        return []
    text = index.normalized
    spans: list[tuple[int, int]] = []
    cursor = text.find(needle)
    while cursor != -1:
        end = cursor + len(needle)
        if (cursor == 0 or text[cursor - 1] == " ") and (end == len(text) or text[end] == " "):
            spans.append(index.to_raw_span(cursor, end))
        cursor = text.find(needle, cursor + 1)
    return spans


def resolve_citation(
    citation: MatterCitation, indexes: dict[str, NormalizedIndex]
) -> CitationResolution:
    """Locate one quote in the document it claims to come from.

    A quote that exists, but in a different document, is reported separately from one
    that exists nowhere. Both fail, for different reasons: the second was invented,
    the first was read and then attributed to the wrong instrument, which in a matter
    means attributing an obligation to the wrong party or the wrong agreement.
    """
    result = CitationResolution(citation.citation_id, citation.document_id, "unsupported")
    index = indexes.get(citation.document_id)
    if index is None:
        result.status = "not_visible"
        return result

    needle = normalize_text(citation.quote)
    spans = find_whole(index, needle)
    if len(spans) == 1:
        result.status, result.span = "grounded", spans[0]
    elif len(spans) > 1:
        result.status = "ambiguous"
    else:
        result.found_in = sorted(
            other for other, other_index in indexes.items()
            if other != citation.document_id and find_whole(other_index, needle)
        )
        if result.found_in:
            result.status = "misattributed"
    return result


def _points_at(quoted: tuple[int, int], passage: tuple[int, int]) -> bool:
    overlap = min(quoted[1], passage[1]) - max(quoted[0], passage[0])
    return overlap > 0 and overlap >= MIN_QUOTE_FOCUS * (quoted[1] - quoted[0])


def _documents_hit(
    issue: MatterIssue, cited: list[CitationResolution]
) -> tuple[int, frozenset[str]]:
    """How many of an issue's evidence spans the citations point at, and in which documents."""
    spans_hit = 0
    documents: set[str] = set()
    for span in issue.evidence:
        if any(
            c.document_id == span.document_id and _points_at(c.span, (span.start, span.end))
            for c in cited
        ):
            spans_hit += 1
            documents.add(span.document_id)
    return spans_hit, frozenset(documents)


def _best(
    cited: list[CitationResolution], issues: Iterable[MatterIssue]
) -> tuple[int, list[tuple[MatterIssue, frozenset[str]]]]:
    """The issues whose evidence the citations point at most, and how many spans that is."""
    candidates = []
    for issue in issues:
        spans_hit, documents = _documents_hit(issue, cited)
        if spans_hit:
            candidates.append((spans_hit, issue, documents))
    if not candidates:
        return 0, []
    best = max(spans_hit for spans_hit, _, _ in candidates)
    return best, [(i, d) for spans_hit, i, d in candidates if spans_hit == best]


def bind_finding(
    finding_id: str,
    task: str,
    evidence_ids: list[str],
    resolutions: dict[str, CitationResolution],
    issues: list[MatterIssue],
    credit_rule: CreditRule = conflict_credit,
    *,
    alternates: list[MatterIssue] | None = None,
    earlier: list[MatterIssue] | None = None,
) -> FindingBinding:
    """Tie one finding to at most one gold issue.

    Every citation the finding names must be grounded. One invented or misattributed
    quote unbinds the whole finding, as in the single-contract path: a conclusion
    resting partly on text that is not there is not partly supported.

    `issues` are the expected issues of the finding's own task. `alternates` are
    tried only when none of those is pointed at. `earlier` are issues from previous
    rounds: a finding that points at one of them better than at anything current is a
    restatement, set aside without credit or penalty.
    """
    binding = FindingBinding(finding_id=finding_id, task=task)
    if not evidence_ids:
        binding.reason = UNBOUND_NO_EVIDENCE
        return binding

    cited = [resolutions[i] for i in evidence_ids]
    if any(c.status == "ambiguous" for c in cited):
        binding.reason = UNBOUND_AMBIGUOUS
        return binding
    if any(c.status != "grounded" for c in cited):
        binding.reason = UNBOUND_UNRESOLVED
        return binding

    hits, winners = _best(cited, issues)
    if not winners and alternates:
        hits, winners = _best(cited, alternates)

    if earlier and _best(cited, earlier)[0] > hits:
        binding.reason = RESTATED
        return binding
    if not winners:
        binding.reason = UNBOUND_NO_ISSUE
        return binding
    if len(winners) > 1:
        # The quoted text belongs equally to several issues. Picking one would award
        # evidence the review never gave.
        binding.reason = UNBOUND_AMBIGUOUS
        return binding

    issue, documents = winners[0]
    binding.issue_id = issue.issue_id
    if issue.task == "conflict":
        required = frozenset(span.document_id for span in issue.evidence)
        binding.credit = max(0.0, min(1.0, float(credit_rule(documents, required))))
        if binding.credit == 0.0:
            binding.reason = ONE_SIDED
    else:
        binding.credit = 1.0
    return binding


def _answerable(
    issue: MatterIssue, visible: frozenset[str], credit_rule: CreditRule
) -> bool:
    """Could any finding earn credit on this issue from the visible documents?

    Asked of the credit rules themselves, so the ceiling cannot disagree with the
    scoring. A position found without the document that changes its answer still
    counts as reachable here; the wrong stance it leads to shows in action accuracy.
    """
    required = frozenset(span.document_id for span in issue.evidence)
    seen = required & visible
    if not seen:
        return False
    if issue.task == "conflict":
        return credit_rule(seen, required) > 0.0
    return True


def _ratio(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_matter(
    documents: dict[str, str],
    gold: MatterGold,
    review: MatterReview,
    split: Split | None = None,
    credit_rule: CreditRule = conflict_credit,
    earlier_issues: Iterable[MatterIssue] = (),
) -> MatterScores:
    """Score one review against one round's answers.

    `documents` are the texts the system was shown under its condition, which is what
    makes a citation to a hidden document fail rather than resolve.

    With `split` set, recall runs over that split's issues only. A finding bound to an
    issue of the other split is left out rather than counted as wrong, and is absent
    from the returned bindings, so a development scorecard reveals nothing about the
    evaluation issues. A finding bound to nothing counts against precision in every
    split, since it belongs to none.

    `earlier_issues` are the answers of previous rounds. A later round's answers list
    what is new, and a review of the whole file will rightly repeat older points.
    Those repetitions are listed and left out of precision. Whether an older point
    still holds after the facts changed is not scored unless the later round's
    answers restate it.
    """
    indexes = {doc_id: build_normalized_index(text) for doc_id, text in documents.items()}
    resolutions = {c.citation_id: resolve_citation(c, indexes) for c in review.citations}

    by_task: dict[str, list[MatterIssue]] = {"conflict": [], "position": [], "escalation": []}
    for issue in gold.issues:
        by_task[issue.task].append(issue)
    earlier_by_task: dict[str, list[MatterIssue]] = {t: [] for t in by_task}
    for issue in earlier_issues:
        earlier_by_task[issue.task].append(issue)

    findings = {
        **{f.finding_id: f for f in review.conflicts},
        **{f.finding_id: f for f in review.positions},
        **{f.finding_id: f for f in review.escalations},
    }

    def alternates(task: str, finding) -> list[MatterIssue]:
        # "This needs a decision above us" and "this cannot be answered yet" are one
        # act filed in two places. A review that files it in the other place has
        # still escalated, so it is not a miss plus a false alarm.
        if task == "position" and finding.action == "escalate":
            return by_task["escalation"]
        if task == "escalation":
            return [i for i in by_task["position"] if i.expected_action == "escalate"]
        return []

    all_bindings: list[FindingBinding] = []
    for task, items in (
        ("conflict", review.conflicts),
        ("position", review.positions),
        ("escalation", review.escalations),
    ):
        for finding in items:
            all_bindings.append(
                bind_finding(
                    finding.finding_id, task, finding.evidence, resolutions,
                    by_task[task], credit_rule,
                    alternates=alternates(task, finding),
                    earlier=earlier_by_task[task],
                )
            )

    selected = [i for i in gold.issues if split is None or i.split == split]
    selected_ids = {i.issue_id for i in selected}
    restated = [b for b in all_bindings if b.reason == RESTATED]
    relevant = [
        b for b in all_bindings
        if b.reason != RESTATED and (b.issue_id is None or b.issue_id in selected_ids)
    ]

    credit: dict[str, float] = {}
    credited: dict[str, list[str]] = {}
    for binding in relevant:
        if binding.issue_id is None or binding.credit <= 0.0:
            continue
        credited.setdefault(binding.issue_id, []).append(binding.finding_id)
        credit[binding.issue_id] = max(credit.get(binding.issue_id, 0.0), binding.credit)

    detected = [i for i in selected if i.issue_id in credit]
    material = [i for i in selected if i.materiality == "high"]

    def recall(issues: list[MatterIssue]) -> float | None:
        return _ratio(sum(credit.get(i.issue_id, 0.0) for i in issues), len(issues))

    # Every credited finding on a position counts. Deciding by the first one would let
    # a review that says both reject and accept score by the order it listed them.
    positions_detected = [i for i in detected if i.task == "position"]
    actions = {
        i.issue_id: {getattr(findings[f], "action", "escalate") for f in credited[i.issue_id]}
        for i in positions_detected
    }
    materialities = {
        i.issue_id: {
            findings[f].materiality for f in credited[i.issue_id]
            if hasattr(findings[f], "materiality")
        }
        for i in detected if i.task in ("conflict", "position")
    }
    graded = [i for i in detected if materialities.get(i.issue_id)]

    escalation_findings = [b for b in relevant if b.task == "escalation"]
    escalations_detected = {
        b.issue_id for b in escalation_findings if b.issue_id and b.credit > 0.0
    }

    referenced = {citation_id for f in findings.values() for citation_id in f.evidence}
    counts = Counter(r.status for r in resolutions.values())
    answerable = [i for i in selected if _answerable(i, frozenset(documents), credit_rule)]

    return MatterScores(
        split=split or "all",
        issues_total=len(selected),
        issues_answerable=len(answerable),
        findings_total=len(relevant),
        issue_recall=recall(selected),
        finding_precision=_ratio(len(detected), len(relevant)),
        material_recall=recall(material),
        task_recall={
            task: recall([i for i in selected if i.task == task]) for task in by_task
        },
        escalation_precision=_ratio(len(escalations_detected), len(escalation_findings)),
        action_accuracy=_ratio(
            sum(1 for i in positions_detected if actions[i.issue_id] == {i.expected_action}),
            len(positions_detected),
        ),
        materiality_accuracy=_ratio(
            sum(1 for i in graded if materialities[i.issue_id] == {i.materiality}),
            len(graded),
        ),
        # Telling the client to accept a material term the answers say must not be
        # accepted is the failure with the highest cost, so it is listed by name.
        false_reassurance=sorted(
            i.issue_id for i in positions_detected
            if i.materiality == "high"
            and i.expected_action != "accept"
            and "accept" in actions[i.issue_id]
        ),
        conflicting_actions=sorted(
            issue_id for issue_id, found in actions.items() if len(found) > 1
        ),
        missed_material=sorted(i.issue_id for i in material if i.issue_id not in credit),
        missed=sorted(i.issue_id for i in selected if i.issue_id not in credit),
        unexpected_findings=sorted(
            b.finding_id for b in relevant if b.reason == UNBOUND_NO_ISSUE
        ),
        restated_findings=sorted(b.finding_id for b in restated),
        unbound_findings={
            b.finding_id: b.reason for b in relevant
            if b.reason and b.reason != UNBOUND_NO_ISSUE
        },
        duplicate_issue_findings=sorted(
            issue_id for issue_id, found in credited.items() if len(found) > 1
        ),
        citations={
            status: counts.get(status, 0)
            for status in ("grounded", "misattributed", "ambiguous", "unsupported", "not_visible")
        },
        # Quotations no finding relies on. They cost nothing to add and would
        # otherwise raise the grounding rate, so they are counted in the open.
        unreferenced_citations=sum(1 for c in review.citations if c.citation_id not in referenced),
        citation_grounding=_ratio(counts.get("grounded", 0), len(resolutions)),
        bindings=relevant + restated,
    )
