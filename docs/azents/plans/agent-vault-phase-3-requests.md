---
title: "Agent Vault Phase 3: Session Requests"
created: 2026-11-28
tags: [vault, agent, security, chat]
---

## Phase Execution Plan

- Phase: `3/3` — Session requests, submission, and external delivery.
- Branch/base: `feat/agent-vault-requests` → `feat/agent-vault-runtime`.
- PR boundary: persistent value-free requests, standalone chat cards and shared dialog, exact channel projection, and completion settlement.
- Inputs: [approved Design](../design/vault-261127-agent-vault.md), [phase 2](agent-vault-phase-2-runtime.md), reviewed phase 2 PR #2648 at `5eb48fc42`.
- Deliverables: the request tool; 24-hour nonblocking request lifecycle; exact conversation and manager authorization on the shared form; once-only submission and original-Session mailbox admission; one exact Discord/Slack post and best-effort original-message edit.
- Non-goals: per-use approval, provider-native value forms, cancellation wake, resend outbox, configurable expiry, automatic reopen, additional data migration.
- Interfaces: Session-owned request row and immutable, value-free timeline anchor; status and submission API scoped to exact Session; queue admission and post-commit routing wake; scheduler over due request rows.
- Approved mechanisms: `M7`, `M8`, `M9`, `M10`, `M11`, `M12` plus `M1` and `M2` for encrypted batch composition.
- Authority: REQ-1, REQ-4, REQ-5; ADR-D1, D2, D4, D5 and D9; [existing mailbox](../spec/execution/mailbox.md), [Session lifecycle](../spec/execution/session-lifecycle.md), [provider delivery](../spec/flow/external-channel-delivery.md).
- Design delta: `None`.
- Removal obligations: none. Verify that ordinary chat, archive and Channel Work behavior is unchanged and no secret-bearing provider, event, or log field is introduced.

| Workstream | Owner | Owned paths | Dependency | Verification |
| --- | --- | --- | --- | --- |
| Lifecycle and atomic writes | Primary agent | Azents RDB, Alembic, Session lifecycle catalog, Vault repositories | Agent Vault storage and mailbox | PostgreSQL deadlines, rollback, duplicate races, source retirement and purge |
| Tool and chat presentation | Primary agent | Azents engine/API/event contracts, generated clients and Web chat | Request authority and status projection | Card identity and focus, authorized explicit dialog, login redirect, terminal refresh |
| Exact provider delivery | Primary agent | Existing adapters, bound routing reads, scheduler | Request status and confirmed delivery identity | Discord/Slack fake provider receipts and setup failure/expiry behavior |
| Integration and wiki | Primary agent | required E2E, Spec Wiki and approved snapshot | Stable integrated phase | E2E evidence, scope audit, final reviewer |

- Integration order: schema/catalog → request creation and settlement → public projection and chat → provider dispatch → integrated validation.
- Independent reviewer: `vault-reviewer` reviews the frozen integrated phase. The primary agent owns corrections and reruns.
- Final validation: scoped type checks, generated clients, migrated PostgreSQL tests, UI/provider E2E, document audit. Carry the phase 2 Runner E2E infrastructure limitation until a real run passes; do not set `implemented` dates or remove the temporary plans merely for a partial result.

### Context checkpoint

- The branch stacks on `5eb48fc42` (#2648).
- The working tree adds migration `44439b9001d3`, Session-owned retention and
  purge, durable request and history creation, elapsed DB expiry, authorized
  atomic batch submission, typed wake-capable admission and post-commit wake.
  Focused application type checking and 118 regression tests passed (including
  migrated PostgreSQL rollback, replay after inbox consumption, non-manager
  denial, visitor-free expiry, and open-anchor retention).
- Public clients were regenerated. Main Web type checking, 855 tests and
  focused lint passed. Batch history snapshots and routing-only invalidation
  preserve the standalone anchor. The independent review found a target
  revocation race during provider dispatch preparation. The last database
  statement now rechecks the exact binding, route, installation and request
  in one snapshot for both effects. PostgreSQL covers binding revocation
  after preparation starts and late receipt settlement without another create.
- The unchanged managed Runner image built successfully with host networking.
  The Phase 2 CLI product E2E passed after correcting datetime serialization
  in the history assertion. The Phase 3 public API/Worker E2E passed after
  allowing the mailbox promotion layer's ordinary value-free correlation fields
  in the completion event. The CLI and public request E2E passed again after
  registering the request tool independently of the Runtime Toolkit.
- Main Web E2E passed for the explicitly opened card/dialog, deep-link intent,
  two-tab settlement and reload. Targeted independent re-review closed the
  provider-authority finding. Discord and Slack publication/edit product E2E
  remains outstanding. Do not infer live provider delivery from database claims
  or mark the snapshot implemented before that verification.
