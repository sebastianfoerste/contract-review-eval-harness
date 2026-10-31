# Metrics

This page defines every row of the scorecard: what it measures, the exact formula and
denominator, the edge cases, and whether it can change a release decision. The
definitions follow the code in `src/contract_eval/scorer.py`,
`src/contract_eval/api.py` (`score_review`, `canonicalise_risk_flags`,
`regression_violations`) and `src/contract_eval/release_certificate.py`
(`REQUIREMENTS`, `case_decision`). If this page and the code disagree, the code is right
and this page is a bug.

Every row is computed by `score_review(source_text, expected, output, alias_mode="on")`.
It is pure: no file access, no network, no model call. The same input always gives the
same scores.

## Inputs and shared rules

- **Gold set** (`expected/<case>.json`): `clause_types` (a list), `risk_flags` (clause
  type to severity, one of `low`, `medium`, `high`), `clause_aliases`, `clause_anchors`
  and optional `thresholds`.
- **Review** (`ReviewOutput`): `clauses`, `risk_flags` and `citations`. Each citation has
  a `quote` and a `clause_type`.
- **Sets, not lists.** Clause and risk metrics compare sets of clause names. A clause
  type predicted twice counts once.

### Alias mapping

With `alias_mode="on"` (the default), each predicted clause name is replaced by
`clause_aliases.get(name, name)` before scoring. This applies to the review's
`clauses` and `risk_flags`, not to the gold set's own names and not to citations. With
`alias_mode="off"`, no alias is applied, so a synonym counts as a different clause.
Aliases are declared in the gold set so the mapping can be reviewed. The gold-set
schema checks only their structure, not that an alias is a genuine synonym.

### Risk-flag canonicalisation

`canonicalise_risk_flags` walks the review's risk flags in order and maps each to its
canonical name. The first flag for a clause sets its severity, and that severity is the
one scored. A later flag for the same clause is recorded as a duplicate. If any later
flag carries a different severity from the first, the clause is also recorded as a
conflict. Both lists are sorted and contain each clause once.

### Normalisation for exact-span matching

Citation grounding and span coverage match text after `normalize_text`:

1. Lower-case the text (`str.lower`).
2. Replace each ASCII punctuation character (`string.punctuation`) and each of
   `“ ” ‘ ’ – —` with a space.
3. Collapse every run of whitespace to one space and trim both ends.

A quote is grounded when its normalised form occurs as one contiguous substring of the
normalised contract. Case, punctuation, line wrapping and spacing do not matter. Word
order and every word do. The search is a plain substring search, so it is not tied to
word boundaries. Other characters, such as `„`, `«`, `»` or `…`, are kept as they are.
A quote that is empty after normalisation is never grounded.

Because the search is a substring search, a short quote is grounded almost anywhere:
`the` matches any contract and `confiden` matches inside `confidential`. Two rows
close that gap. Short citations counts grounded quotes under a three-word floor, and
risk flags without evidence asks whether a grounded quote sits inside each flagged
clause.

### Short and partial quotes

Grounding is a substring test, so it accepts any quote whose normalised characters
occur somewhere in the contract. A one-word quote such as `the`, or a fragment inside a
word such as `confiden`, counts as grounded. Span coverage would show that such quotes
engage with no clause, but it is a diagnostic and does not gate release. Under policy
v2, a review of the bundled NDA that names every gold clause and risk correctly and
gives every citation the quote `the` scored citation grounding 1.0, hallucination
count 0 and span coverage 0.0, and was decided `PILOT_ELIGIBLE`. Policy v2.1 decides
the same review `REJECT`: every citation is counted as short, so the `citation.length`
blocker fires, and every flagged clause is listed as a risk flag without evidence. To
reproduce:

```bash
uv run python -c "
import json
from contract_eval.api import evaluate_review
g = json.load(open('expected/nda.json'))
r = {'clauses': [{'clause_type': c, 'text': 'x'} for c in g['clause_types']],
     'risk_flags': [{'clause_type': k, 'severity': v, 'rationale': 'x'} for k, v in g['risk_flags'].items()],
     'citations': [{'quote': 'the', 'clause_type': c} for c in g['clause_types']]}
res = evaluate_review(r, 'nda')
print(res.verdict, res.scores['citation_grounding'], res.scores['span_coverage'])"
```

It prints `REJECT 1.0 0.0`.

## Clause precision

Share of the predicted clause types that the gold set declares.

- Formula: `|expected ∩ predicted| / |predicted|`, over the set of gold `clause_types`
  and the set of canonicalised predicted clause types.
- Denominator: distinct predicted clause types.
- Edge cases: no predicted clause gives 0.0.
- Release policy: requirement `clause.precision`, value must be at least 1.0. Below that,
  review item `unexpected_clause_extracted`, so `HUMAN_REVIEW_REQUIRED`.

## Clause recall

Share of the gold clause types that the review found.

- Formula: `|expected ∩ predicted| / |expected|`.
- Denominator: distinct gold clause types.
- Edge cases: an empty gold `clause_types` gives 0.0.
- Release policy: requirement `clause.recall`, value must be at least 1.0. Below that,
  review item `expected_clause_missed`, so `HUMAN_REVIEW_REQUIRED`.

## Clause F1

Harmonic mean of clause precision and recall.

- Formula: `2 * P * R / (P + R)`.
- Edge cases: 0.0 when `P + R` is 0.
- Release policy: diagnostic only; it never changes the decision.
- Regression gate: fails below the `f1` threshold (default 0.85).

## Risk precision

Share of the flagged clauses that the gold set treats as risks. An over-flagging review
loses precision.

- Formula: `|expected ∩ predicted| / |predicted|`, over the clause names in the gold
  `risk_flags` and the canonicalised predicted flags. Severity plays no part.
- Denominator: distinct canonical clauses the review flagged.
- Edge cases: nothing flagged gives 1.0 (there is no false positive). Nothing expected
  but something flagged gives 0.0.
- Release policy: requirement `risk.precision`, value must be at least 1.0. Below that,
  review item `risk_false_positive`, so `HUMAN_REVIEW_REQUIRED`.

## Risk recall

Share of the gold risks that the review flagged, at any severity.

- Formula: `|expected ∩ predicted| / |expected|`.
- Denominator: distinct gold risk clauses.
- Edge cases: nothing expected gives 1.0 (there was nothing to miss). Something expected
  and nothing flagged gives 0.0.
- Release policy: requirement `risk.recall`, value must be at least 1.0. Below that,
  review item `expected_risk_missed`, so `HUMAN_REVIEW_REQUIRED`.

## Risk F1

Harmonic mean of risk precision and recall.

- Formula: `2 * P * R / (P + R)`.
- Edge cases: 0.0 when `P + R` is 0. Nothing expected and nothing flagged gives 1.0,
  because precision and recall are both 1.0.
- Release policy: diagnostic only.

## Severity accuracy

Share of the jointly identified risks that carry the gold severity. It is measured only on
clauses both sides flagged, so a wrong severity stays separate from a missed risk.

- Formula: `|{k in expected ∩ predicted : predicted[k] == expected[k]}| / |expected ∩ predicted|`.
- Denominator: clauses flagged by both the gold set and the review.
- Edge cases: no jointly identified risk gives 0.0. This includes a review that
  correctly flags nothing on a contract whose gold set has no risks.
- The JSON output also carries `risk_severity_confusion`: counts of `expected->predicted`
  severity pairs over the jointly identified risks.
- Release policy: requirement `risk.severity`, value must be at least 1.0. Below that,
  review item `risk_severity_mismatch`, so `HUMAN_REVIEW_REQUIRED`.

## Risk false positives

The clauses the review flagged that the gold set does not treat as risks:
`sorted(predicted - expected)`. The scorecard shows the count; the JSON output lists the
names in `risk_false_positives`.

- Release policy: the list itself is diagnostic. It is non-empty exactly when risk
  precision is below 1.0, which raises `risk_false_positive`.

## Risk missed

The gold risks the review did not flag: `sorted(expected - predicted)`. The scorecard
shows the count; the JSON output lists the names in `risk_missed`.

- Release policy: the list itself is diagnostic. It is non-empty exactly when risk
  recall is below 1.0, which raises `expected_risk_missed`.

## Duplicate / conflicting flags

Two counts, shown as `duplicates / conflicts`, from risk-flag canonicalisation (see
above). A duplicate is a clause flagged more than once after alias mapping, for example
`sub_processors` and `subprocessors` when the gold set declares one as an alias of the
other. A conflict is a duplicate whose flags carry more
than one severity. Every conflict is also a duplicate. With `alias_mode="off"`, two
synonyms are different clauses and do not count as duplicates.

- Release policy: requirement `risk.duplicates`, the list must be empty, otherwise review
  item `duplicate_risk_flags`. Requirement `risk.conflicts`, the list must be empty,
  otherwise review item `conflicting_risk_flags`. Either gives `HUMAN_REVIEW_REQUIRED`.

## Risk flags without evidence

The flagged clauses with no grounded citation inside them. Risk precision and recall
compare labels; this asks whether the review quoted from the clause it flagged. The
scorecard shows the count; the JSON output lists the names in
`risk_flags_without_evidence`.

- A clause is listed when it is among the canonicalised predicted flags (see alias
  mapping), has an anchor in `clause_anchors` that is found in the contract, and no
  grounded citation overlaps its region. The region is the one span coverage uses:
  from the clause's anchor to the start of the next located anchor in document order,
  or to the end of the contract for the last one.
- Formula: `sorted({k in predicted : k has a located anchor and no grounded citation
  overlaps its region})`.
- Denominator: none; it is a list.
- Edge cases: a flagged clause with no anchor, or whose anchor is not found, is not
  listed. A flag the gold set does not declare has no anchor and is already a risk
  false positive. Ungrounded citations are no evidence. A grounded quote counts as
  evidence whatever its length, so a one-word quote inside the clause satisfies this
  row; that quote is caught by short citations instead. A review with no flags gives
  an empty list. The citation's own `clause_type` plays no part.
- Release policy: requirement `risk.evidence`, the list must be empty. Otherwise review
  item `risk_flag_without_evidence`, so `HUMAN_REVIEW_REQUIRED`.

## Span coverage

Share of the gold clauses with at least one grounded citation inside them. It ignores the
review's clause labels, so it measures where the review quoted, not what it called
things. It measures citation placement, not whether the conclusion about the clause is
right.

- Each gold clause is located by its verbatim anchor in `clause_anchors`: the first
  occurrence of the normalised anchor in the normalised contract. `make anchor-check`
  checks that every anchor occurs exactly once.
- A clause's region runs from its anchor to the start of the next located anchor in
  document order, or to the end of the contract for the last one. Text before the first
  anchor belongs to no clause.
- A clause is covered when the span of any grounded citation overlaps its region.
  Ungrounded citations are ignored. The citation's own `clause_type` plays no part.
- Formula: `covered clauses / number of entries in clause_anchors`.
- Denominator: gold clauses with an anchor.
- Edge cases: an anchor not found in the contract counts as uncovered. No anchors gives
  0.0. The JSON output lists uncovered clauses in `span_uncovered_clauses`.
- Release policy: diagnostic only.

## Citation grounding

Share of the review's citations whose quote is an exact span of the normalised contract
(see normalisation above).

- Formula: `grounded citations / all citations`. The scorecard shows both counts.
- Denominator: every citation in the review, including duplicates.
- Edge cases: a review with no citations gives 0.0. A quote that is empty after
  normalisation is not grounded. Grounding checks only that the quote occurs somewhere
  in the contract, not that it sits in the clause named by the citation, and not that
  it is long enough to identify a passage; see short citations.
- Release policy: requirement `citation.grounding`, value must be at least 1.0. Below
  that, blocker `citation_grounding_below_100_percent`, so `REJECT`. A review with no
  citations is therefore rejected.
- Regression gate: fails below the `grounding_rate` threshold (default 0.75).

## Hallucination count

The number of citations whose quote is not grounded in the contract, using the same test
as citation grounding. It equals `all citations - grounded citations`.

- Edge cases: a review with no citations gives 0.
- Release policy: requirement `citation.unsupported`, value must be zero. Otherwise
  blocker `unsupported_citation_detected`, so `REJECT`. One fabricated quote is enough.
- Regression gate: fails above the `hallucinations` threshold (default 1), so the
  bundled stub, with one fabricated quote, passes the regression gate and is still
  rejected by the release policy.

## Short citations

The number of grounded citations whose quote has fewer than three words. A one- or
two-word match is grounded almost anywhere and identifies no passage, so it is not a
quotation. The floor is `MIN_QUOTE_WORDS` in `scorer.py`.

- Formula: `|{c in citations : c is grounded and |words(normalise(c.quote))| < 3}|`,
  where the words are the whitespace-separated tokens of the normalised quote.
- Denominator: none; it is a count.
- Edge cases: an ungrounded citation is a hallucination and is not counted here, so no
  citation is counted twice. A fragment such as `confiden` is grounded inside
  `confidential` and counts as one word. A review with no citations gives 0. Three
  words is the lowest floor that clears every committed output: the shortest live
  quote has three words and the shortest stub quote has four, so the floor changes no
  committed decision, and a floor of four would reject the live DPA output.
- Release policy: requirement `citation.length`, value must be zero. Otherwise blocker
  `degenerate_citation_detected`, so `REJECT`.
- Regression gate: not part of it.

## Risk-flag accuracy (legacy)

Share of the gold risks predicted at the gold severity.

- Formula: `|{k in expected : predicted.get(k) == expected[k]}| / |expected|`.
- Denominator: gold risk clauses.
- Edge cases: nothing expected gives 0.0.
- It is blind to false positives: a review that adds twenty spurious flags scores the
  same as one that adds none. Read it next to risk precision, never on its own.
- Release policy: excluded from release decisions; published only as a diagnostic.
- Regression gate: fails below the `risk_accuracy` threshold (default 0.45).

## Release policy

Policy `contract-review-eval.strict-legal-release-policy.v2.1`. The registry
`REQUIREMENTS` in `src/contract_eval/release_certificate.py` is the single source of
truth. Policy v2.1 is policy v2 plus `citation.length` and `risk.evidence`; a
certificate issued under v2 is still verified under the v2 registry.

| Requirement | Score | Condition | Class | Failure code |
|---|---|---|---|---|
| `citation.grounding` | `citation_grounding` | at least 1.0 | blocker | `citation_grounding_below_100_percent` |
| `citation.unsupported` | `hallucination_count` | zero | blocker | `unsupported_citation_detected` |
| `citation.length` | `citation_short_count` | zero | blocker | `degenerate_citation_detected` |
| `clause.precision` | `clause_precision` | at least 1.0 | review item | `unexpected_clause_extracted` |
| `clause.recall` | `clause_recall` | at least 1.0 | review item | `expected_clause_missed` |
| `risk.precision` | `risk_precision` | at least 1.0 | review item | `risk_false_positive` |
| `risk.recall` | `risk_recall` | at least 1.0 | review item | `expected_risk_missed` |
| `risk.severity` | `risk_severity_accuracy` | at least 1.0 | review item | `risk_severity_mismatch` |
| `risk.duplicates` | `risk_duplicate_flags` | empty | review item | `duplicate_risk_flags` |
| `risk.conflicts` | `risk_conflicting_flags` | empty | review item | `conflicting_risk_flags` |
| `risk.evidence` | `risk_flags_without_evidence` | empty | review item | `risk_flag_without_evidence` |

`case_decision` decides one case:

- any blocker: `REJECT`;
- otherwise any review item: `HUMAN_REVIEW_REQUIRED`;
- otherwise: `PILOT_ELIGIBLE`.

A suite takes the worst case decision. Clause F1, risk F1, legacy risk-flag accuracy, the
false-positive and missed lists, the severity confusion, span coverage and the citation
counts are published as diagnostics and never change the decision. `PILOT_ELIGIBLE`
means eligible for a supervised pilot; it never authorises relying on a review without a
lawyer.

## Demo regression gate

Policy `demo-regression-policy.v2`, applied by `regression_violations`. It is calibrated
to the deliberately imperfect bundled stub, so it detects change, not fitness for use.
`contract-eval evaluate` fails on a violation unless `--no-gate` is passed;
`ReviewResult.failures("regression")` and the pytest plugin with `policy="regression"`
use the same function. The plugin's default policy is the release policy.

| Threshold key | Score | Violation when | Default |
|---|---|---|---|
| `f1` | `clause_f1` | below the threshold | 0.85 |
| `risk_accuracy` | `risk_flag_accuracy` | below the threshold | 0.45 |
| `grounding_rate` | `citation_grounding` | below the threshold | 0.75 |
| `hallucinations` | `hallucination_count` | above the threshold | 1.0 |

A gold set can override any default through its `thresholds` field. None of the bundled
gold sets does.
