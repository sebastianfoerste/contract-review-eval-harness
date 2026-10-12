<!-- Replacement for /Users/sebastian/Developer/active/contract-review-eval-harness/CLAUDE.md (same change for the worktree copy under _wt/harness-candidate-cases). Draft of 2026-09-24. A gstack upgrade may re-add its default routing block; check the diff after upgrades. -->
@AGENTS.md

## Skill routing

When a request matches one of these purposes, invoke that gstack skill with the Skill tool. Otherwise work directly.

- Product ideas and brainstorming: /office-hours
- Strategy and scope: /plan-ceo-review
- Architecture: /plan-eng-review
- Design system or plan review: /design-consultation or /plan-design-review
- Full review pipeline: /autoplan
- Bugs and errors: /investigate
- QA and testing site behaviour: /qa or /qa-only
- Code review and diff checks: /review
- Visual polish: /design-review
- Ship, deploy or PR: /ship or /land-and-deploy, with Sebastian's go for each external step
- Save progress: /context-save; resume context: /context-restore
- Backlog-ready spec or issue: /spec
