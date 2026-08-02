---
title: "Provider Channel Participation Phase 7 — Spec Promotion"
created: 2026-08-02
tags: [external-channel, conversation, documentation, spec]
---

# Provider Channel Participation Phase 7 — Spec Promotion

## Phase Execution Plan

- Phase: `7 — Spec Promotion`
- Branch/base: `feature/conversation-channel-participation-spec` → `feature/conversation-channel-participation-validation`
- PR boundary: Promote the verified provider channel participation behavior into current Living Specs, record the actual implementation date on the Requirements and Design snapshot, and preserve the accepted ADR unchanged.
- Inputs: Approved `conversation-260801` Requirements, accepted ADR, Design, multi-phase implementation plan, PRs 3–8, the integrated validation checkpoint, removal audit, and independent review evidence.
- Deliverables: Current External Channel domain, Agent/Workspace management, provider ingress, authorization, delivery, lifecycle, and E2E strategy specs aligned with the integrated implementation; matching `implemented: 2026-08-02` markers on Requirements and Design; a recorded no-update finding for broad `code_paths` matches whose behavior did not change.
- Non-goals: Production or test code changes, OpenAPI/client regeneration, migration changes, accepted ADR edits, new product decisions, rollout-gate removal, implementation-plan cleanup, PR merge, or live infrastructure mutation.
- Interfaces: Living Specs describe only current behavior and retain their existing structure and code links. Requirements and Design receive only the verified implementation marker and then become immutable with the accepted ADR. Documentation remains English.
- Removal obligations: None in this phase. PR 8 verified every Design removal obligation and recorded executable absence evidence.
- Absence verification: Search updated specs for stale authoritative claims that parent invocations immediately create a Binding/Session, every Discord root provisions a thread, Allow always enters Binding replay, presence contains only `View session`, or Multi default changes ignore parent participation. Confirm no code or accepted ADR diff.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Spec impact classification | `/root` | Integrated diff and `docs/azents/spec/**/*.md` | PR 8 stable checkpoint | Exact update/no-update set grounded in `code_paths` and behavior | Full stack changed-path mapping, stale-claim search |
| Living Spec promotion | `/root` | `docs/azents/spec/domain/{external-channel,agent,workspace}.md`, `docs/azents/spec/flow/{external-channel-provider-ingress,external-channel-authorization,external-channel-delivery,external-channel-lifecycle,test-strategy-e2e-primary}.md` | Completed classification | Current parent participation, provider controls, management, rollout, and deterministic validation contract | Frontmatter validation, content comparison, stale-claim search |
| Snapshot implementation marker | `/root` | `docs/azents/requirements/conversation-260801-provider-channel-participation.md`, `docs/azents/design/conversation-260801-provider-channel-participation.md` | Verified PR 8 implementation and review | Matching `implemented: 2026-08-02` markers; no accepted ADR change | Snapshot validator and diff audit |
| Independent review and integration | `/root` with `/root/pr7-lifecycle-independent-review-20260801` | Stable documentation diff | Completed spec and snapshot updates | Read-only correctness/completeness review and final clean documentation diff | Targeted re-review when required, pre-commit docs hooks, `git diff --check` |

- Integration order: Record and report this plan; classify full-stack spec impact; update the External Channel domain first; align ingress and authorization; align delivery and lifecycle; align Agent/Workspace management and E2E strategy; add matching implementation markers; run stale-authority and scope searches; request independent review; apply grounded corrections; run final documentation validation; commit and open PR 9.
- Independent review: `/root/pr7-lifecycle-independent-review-20260801` performs a read-only review against the integrated implementation, PR 8 evidence, Requirements, ADR, Design, and current spec rules. Review prioritizes missing or contradictory current behavior, accidental new product decisions, incorrect rollout claims, removal obligations still described as authoritative, immutable snapshot handling, and unrelated spec churn.
- Final validation: Documentation frontmatter and snapshot validation through pre-commit; generated docs index hook; stale-claim searches; exact Requirements/Design implementation-date match; accepted ADR no-diff check; changed-path/scope audit; `git diff --check`.
- Scope-drift check: The branch must contain only this Phase 7 plan, affected Living Specs, their generated documentation indexes, and the matching Requirements/Design markers. Remove production/test/client/migration changes, accepted ADR edits, plan deletions, unrelated freshness-only spec updates, or speculative future behavior.
- Spec-review no-update findings: `docs/azents/spec/domain/conversation.md` already describes canonical External Channel mailbox/event projection and role-based continuation, so the matched config/UI-test paths require no prose change. `docs/azents/spec/domain/goal.md` matched only the shared continuation presentation test and has no Goal behavior change. Other broad `code_paths` matches outside the eight updated specs are implementation support, generated-client, rollout, or test paths whose current owning specs remain accurate.
- Context checkpoint: Updated External Channel, Agent, Workspace, ingress, authorization, delivery, lifecycle, and E2E strategy specs; left Conversation and Goal unchanged after explicit comparison; recorded matching `implemented: 2026-08-02` markers. Stale-authority searches and accepted-ADR/no-production-code scope checks passed. Documentation index generation/check, 14 snapshot-validator tests, pre-commit file hooks, and `git diff --check` passed. Independent read-only review found one Slack-options scope overstatement; the correction now records authenticated Slack `block_suggestion` as unsupported while retaining Discord options, and targeted re-review reported no remaining Critical/Warning findings. PR 10 still owns removal of the implementation and phase plans.
