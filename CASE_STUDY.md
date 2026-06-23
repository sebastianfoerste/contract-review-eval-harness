# Case Study: Contract Review Evaluation Harness

## Legal problem

AI assisted contract review can produce outputs that sound plausible but miss required issues, overstate conclusions, cite weak sources or invent findings.

For legal work, this is not merely a drafting problem. It is a quality control problem.

## Product problem

Legal AI products need repeatable ways to test whether an output is complete, grounded and safe for human review. A reviewer should be able to see what was expected, what was found, what was missing and where citations or assumptions need attention.

## Workflow design

The harness compares AI assisted contract review outputs against expected answer sets. It checks coverage, grounding and hallucination indicators, then creates a human review checklist.

The intended workflow is:

1. Define the expected review issues for a synthetic contract scenario
2. Run or import an AI assisted review output
3. Compare the output against expected issues
4. Check whether cited support exists
5. Flag potential hallucinations or unsupported findings
6. Produce a review checklist for a human lawyer

## AI risk addressed

The project addresses several common legal AI risks:

1. Missing material issues
2. Unsupported conclusions
3. Citation mismatch
4. Hallucinated risk findings
5. Overconfident drafting
6. Reviewer fatigue caused by fluent but unreliable text

## Human review model

The tool is not designed to replace legal judgment. It is designed to make review more structured by showing the reviewer where the output appears complete, where it may be unsupported and where additional attention is required.

The human reviewer remains responsible for final judgment, legal interpretation and client ready output.

## Evaluation or quality control

The core quality mechanism is repeatable comparison against expected answer coverage and citation grounding. This turns legal AI assessment from a subjective impression into a visible review artifact.

## What I would improve next

1. Add more synthetic contract scenarios across different clauses
2. Add severity weighting for missed issues
3. Add richer citation span checks
4. Add a simple report export
5. Add screenshots or terminal output examples to the README
6. Add a small benchmark table comparing model outputs across the same expected answer set

## Relevance for Legal Engineer / Product Specialist roles

This project demonstrates that I understand legal AI quality as a product and workflow challenge, not just as a prompting challenge.

It is especially relevant for roles that require legal domain expertise, evaluation design, customer trust, source grounding and product feedback loops for professional services AI.
