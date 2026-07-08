---
title: "Codex-first Subagent Implementation Plan"
created: 2026-07-08
updated: 2026-07-08
tags: [backend, frontend, engine, api, documentation]
---
# Codex-first Subagent Implementation Plan

## Summary

This plan ships the actual new subagent model after the prerequisite stack is complete. It assumes the prerequisite stack has already established input producer/wake boundaries, toolkit execution-mode filtering groundwork, head-bound context fork helpers, FilePart placeholders, and root `SessionAgentContext` ownership for Projects/worktrees.

This stack focuses only on subagent behavior: child/nested `SessionAgent` domain, agent mailbox input, collaboration tools, child scheduling, wait/interrupt/stop semantics, projection API, frontend tree/detail surfaces, spec promotion, and final cleanup.

## Design Link

- [Codex-first Subagent Redesign Implementation Design](codex-first-subagent-redesign.md)
- [Codex-first Subagent Prerequisites Implementation Plan](codex-first-subagent-prerequisites-implementation-plan.md)
- [ADR-0096: Codex-first Subagent Redesign](../adr/0096-codex-first-subagent-redesign.md)

## Stack Prefix

`subagent`

## Entry Criteria

- The prerequisite ship-feature stack has all planned PRs opened.
- CI monitoring for the prerequisite stack has completed or failures are understood.
- The prerequisite final mapping table shows no open prerequisite gaps.
- Root session behavior continues to pass Project/worktree/input/toolkit regression checks.

## PR Stack

### PR 1 — Child SessionAgent domain foundation

Scope:

- Support child and nested `SessionAgent` rows under an existing root tree.
- Enforce `(root_session_agent_id, path)` and `(parent_session_agent_id, name)` uniqueness.
- Strictly validate child names.
- Create child `SessionAgent` and linked child `AgentSession` atomically.
- Keep child `AgentSession` rows hidden from ordinary session lists via `session_kind = subagent`.
- Add repository/domain APIs for tree lookup, path resolution, child creation, descendant enumeration, and observation cursor updates.
- Add terminal result projection fields to `agent_runs` if not already provided by the prerequisite stack.
- Do not register model-visible collaboration tools yet.

Validation:

- Repository/model tests for root, child, nested child, invalid names, duplicate siblings, out-of-tree lookup, and cascade ownership.
- Session list tests verifying child sessions are hidden.

### PR 2 — Agent mailbox input and collaboration tools

Scope:

- Implement agent mailbox input producer using target child input buffers.
- Add `agent_message` event kind and model lowering.
- Implement the bundled collaboration Toolkit:
  - `spawn_agent`
  - `send_message`
  - `followup_task`
  - `wait_agent`
  - `interrupt_agent`
  - `list_agents`
- Register the tool bundle only when all six baseline tools are coherent.
- Keep `spawn_agent.agent_type` omitted/default-only.
- Wire the prerequisite context fork helper and FilePart placeholder behavior.
- Keep `send_message` queue-only and `followup_task` wake-producing.
- Keep `interrupt_agent` target-scoped, no-close, no-delete.

Validation:

- Tool tests for valid spawn, invalid name, duplicate child, unsupported agent type, missing target, out-of-tree target, default `fork_turns`, and FilePart placeholder fork.
- Mailbox producer tests for queue-only vs wake-producing behavior.
- Event lowering tests for `agent_message` source labeling.
- `list_agents` projection tests for root, child, nested child, status, and `last_task_message`.

### PR 3 — Worker scheduling, terminal results, wait cursors, stop, and recovery

Scope:

- Schedule child sessions as independent `AgentSession` runs through existing worker/broker mechanics.
- Finalize child run terminal result projections during run finalization.
- Implement `wait_agent` observation cursor advancement only for returned terminal results.
- Implement root user-facing subtree stop.
- Implement child detail/control subtree stop.
- Preserve model-visible `interrupt_agent` as target-only and non-descendant-propagating.
- Ensure parent run retry/recovery does not mutate child runs and child retry/recovery does not mutate parent run state.

Validation:

- Worker tests for spawn wake-up, followup wake-up, send queue-only behavior, terminal projection finalization, wait cursor advancement, timeout/no-result behavior, and failed child run observation.
- Stop/recovery tests for root subtree stop, child subtree stop, target interrupt, parent retry independence, and child retry independence.

### PR 4 — Subagent Tree projection API and live invalidation

Scope:

- Add dedicated Subagent Tree projection API for a root `SessionAgent` tree.
- Project nested tree shape, canonical paths, status, last task/message preview, unread/observed result indicators, and child detail links.
- Keep root chat `/live` from embedding the full tree.
- Add non-durable live invalidation/update signal such as `subagent_tree_changed`.
- Ensure refresh/reconnect reconstructs the same state from DB projection.

Validation:

- API tests for root tree, nested tree, hidden child session access, out-of-tree authorization, unread indicator, and reconnect/refetch behavior.
- Live signal tests verifying it is not the source of truth.
- OpenAPI/client regeneration if public API changes.

### PR 5 — Frontend tree, tool cards, and child detail surfaces

Scope:

- Render parent chat subagent coordination through ordinary tool call/result cards.
- Add desktop Subagent Tree panel/section.
- Add quick child detail surface from the parent session UI.
- Add full child detail route for long transcripts, refresh, deep links, and debugging.
- Add mobile full-height drawer or dedicated screen for the tree.
- Add mobile full-screen child detail view with a clear back path.
- Keep child sessions hidden from ordinary Agent session lists.

Validation:

- Component tests for tree rendering, status, unread indicators, and child detail entry points.
- Route/navigation tests for hidden child sessions and direct authorized child detail links.
- Mobile layout/navigation tests.
- TypeScript format, lint, typecheck, and build.

### PR 6 — E2E/testenv validation and implementation mapping gap closure

Scope:

- Add or update testenv fixtures for root + child/nested `SessionAgent` trees and controllable child behavior.
- Run the planned E2E scenarios.
- Inspect actual code against ADR-0096, the overall design, and this implementation plan.
- Produce an ADR/requirements-to-code mapping table.
- Start from the assumption that implementation gaps may exist until verified against code.
- Fix every discovered behavior gap in this PR or amend/rebase the responsible earlier PR.

Required mapping columns:

| Source | Requirement | Expected code path(s) | Observed implementation | Status | Gap/fix PR |
| --- | --- | --- | --- | --- | --- |

Required E2E scenarios:

- Root agent spawns one child and observes it through `wait_agent`.
- Child receives `send_message` without wake and later processes queued context through `followup_task`.
- Nested child spawn appears in the same root tree projection.
- `interrupt_agent` interrupts only the target child current run.
- Root stop interrupts all running descendants.
- Child detail stop interrupts that child subtree.
- Browser refresh/reconnect reconstructs the same tree from the dedicated projection API.
- Child transcript detail opens from parent tree and reads child session history.
- Mobile tree/detail navigation uses drawer/full-screen flow with a clear back path.

Completion rule:

- This subagent ship-feature is not complete until every required row is `Implemented` or explicitly `Deferred` with a reason outside the shipped scope, and all in-scope gaps are fixed.

### PR 7 — Spec promotion

Scope:

- Run `/spec-review`.
- Update living specs under `docs/azents/spec/` for implemented current behavior.
- Mark the overall design implemented only after validation and gap closure are complete.
- Add a new ADR only if implementation discovers a hard-to-reverse decision not already captured by ADR-0096.

Likely affected specs:

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/domain/conversation.md`
- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/chat-session-resync.md`
- `docs/azents/spec/flow/file-exchange-storage.md`
- `docs/azents/spec/flow/test-strategy-e2e-primary.md`

Validation:

- Docs index check.
- Spec frontmatter/code path validation through docs index tooling.
- Focused tests for any spec-driven corrections made in this PR.

### PR 8 — Cleanup

Scope:

- Remove stale temporary implementation plan documents if specs and implemented design now provide the source of truth.
- Remove temporary validation reports if they are superseded by PR evidence/specs.
- Keep adopted ADR history immutable.
- Do not mix behavior changes or refactors into cleanup.

Validation:

- Docs index check.

## Dependencies

- This stack depends on the prerequisite stack.
- PRs are stacked in order.
- CI monitoring starts only after all planned subagent PRs are opened.

## Data/API/Runtime Changes by Phase

| Phase | Data changes | API changes | Runtime/worker changes | UI changes |
| --- | --- | --- | --- | --- |
| PR 1 | child/nested `SessionAgent`; child session domain | none or internal only | none | none |
| PR 2 | `agent_message`; observation metadata use | model-visible collaboration tools | mailbox input producer | tool cards may remain generic |
| PR 3 | terminal result projection use | stop/control behavior if exposed | child scheduling, terminal finalization, stop/recovery | none |
| PR 4 | projection queries | Subagent Tree API; live invalidation | none | client contract only |
| PR 5 | none | consume generated clients | none | tree/detail/mobile surfaces |
| PR 6 | fixtures/evidence as needed | none unless gaps require fixes | E2E-driven fixes | E2E-driven fixes |
| PR 7 | spec docs only | docs/spec updates | docs/spec updates | docs/spec updates |
| PR 8 | cleanup docs only | none | none | none |

## Security and Permission Requirements

- Existing workspace membership and Agent access checks apply to root and child surfaces.
- Child sessions cannot be controlled across root trees.
- Child detail links require authorization through the root tree context or direct authorized deep link behavior.
- Subagents inherit configured access, not parent run toolkit instances.
- Memory Write and Goal Toolkit remain excluded from subagent-mode auto-binding.

## Rollout

No feature flag. Each surface is exposed directly when its phase reaches a coherent usable boundary. Before then, code remains unexposed by not registering incomplete endpoints/tools/UI routes.

## CI Policy

- Create all planned PRs in this stack before starting CI monitoring.
- Record commands and CI status in each PR body or final validation PR.
- If a gap/failure requires amending an earlier PR, rebase/retarget following stack branches before rechecking CI.

## Cleanup Policy

The cleanup PR removes temporary implementation planning artifacts after specs are current and the design is marked implemented. ADR-0096 remains as decision history.
