---
title: "Automatic Session Default Projects Phase 6 Spec Promotion"
created: 2026-07-24
tags: [agent, session, workspace, external-channel, documentation, spec]
---
# Automatic Session Default Projects — Phase 6 Spec Promotion

## Phase Execution Plan

- Phase: `6 — Living Spec promotion`
- Branch/base: `feat/agent-default-projects-spec` →
  `feat/agent-default-projects-validation`
- PR boundary: Promote the verified implementation into current Living Specs and
  mark the Requirements and primary Design implemented with the same KST date.
- Inputs: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md),
  [`agent-260724/ADR`](../adr/agent-260724-automatic-session-default-projects.md),
  [`agent-260724/DESIGN`](../design/agent-260724-automatic-session-default-projects.md),
  the [Phase 5 validation report](../design/agent-260724-automatic-session-default-projects-validation-report.md),
  the [multi-phase implementation plan](agent-260724-automatic-session-default-projects-implementation-plan.md),
  and the implementation stack through PR 7.
- Deliverables:
  - Update Agent and Workspace specs with policy ownership, persistence, ordered
    normalized paths, optimistic revision semantics, AgentAdmin authorization,
    Runtime-backed non-empty replacement validation, empty clear, and separation
    from recency/catalog projections.
  - Update Conversation and Workspace specs so authoritative Project membership is
    owned by `SessionAgentContext`, exposed through Session-scoped compatibility
    APIs, and inherited by subagents without duplicate registration.
  - Update Conversation with the explicit/default root workspace intent boundary,
    Runtime-free snapshot creation, team-primary insert-winner behavior, and
    immutable existing Session snapshots.
  - Update External Channel domain and authorization/provider-ingress flows for
    Allow-created and already-granted initial-binding snapshots plus existing
    binding reuse.
  - Add `implemented: 2026-07-24` to the Requirements and primary Design. Do not
    modify the accepted ADR.
- Non-goals: Product or API behavior changes, Runtime Provider contract lifecycle
  work, E2E fixture changes, generated-client edits, validation-report rewriting,
  or plan cleanup.
- Validation:
  - Run the repository spec-review comparison against the implementation stack.
  - Validate documentation frontmatter and development-snapshot lifecycle through
    targeted pre-commit hooks.
  - Confirm each changed spec has current `code_paths`, `last_verified_at`, and an
    incremented `spec_version`.
  - Confirm Requirements and Design use the same implementation date and the ADR
    has no diff.
  - Run `git diff --check`.
- Scope-drift check: Compare the branch against
  `feat/agent-default-projects-validation`. The expected diff is this phase plan,
  the six promoted Living Specs, and the matching Requirements/Design
  implementation dates, plus the two generated documentation indexes.
