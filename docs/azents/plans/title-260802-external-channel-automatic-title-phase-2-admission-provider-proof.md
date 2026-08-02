---
title: "External Channel Automatic Title Phase 2 Admission and Provider Proof Execution Plan"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, discord, title, backend, worker]
---

# Phase Execution Plan

- Phase: `2 — Admission and provider proof`
- Branch/base:
  `feat/external-channel-title-admission-proof` →
  `azents/roast-inherit-few`
- PR boundary: Activate exact new-Session title artifacts from both production
  creation paths, persist fail-closed Discord admission observation, and reconcile
  candidate-aware thread provisioning through direct or adoption provider proof.
- Inputs:
  - approved `title-260802/REQ`;
  - accepted `title-260802/ADR-D1` through `ADR-D6`;
  - approved `title-260802/DESIGN` revision `5`;
  - Phase 1 candidate/projection schema and repository contracts from PR #1093;
  - current External Channel ingestion, access, Discord history/delivery, and
    provider-control Worker behavior.
- Deliverables:
  - bounded credential-free exact-root Discord observation with
    `thread_absent`, `thread_present`, or fail-closed `unknown`;
  - one shared idempotent title-artifact boundary used by ordinary ingestion and the
    Access-Allow replay path;
  - exact candidate creation only for the trigger-created root Session and qualifying
    Discord projection creation only for a root-message Resource;
  - unchanged immediate mailbox admission, Session running transition, initial
    controls, commit, wake, AgentRun, and ordinary delivery;
  - candidate-aware current provisioning that always uses the stored provisional
    title;
  - GET-first direct creation proof and complete admission-evidence adoption proof;
  - usable but insufficiently proven threads recorded as canonical delivery targets
    with projection provisioning `unmanaged` and title `relinquished`;
  - persisted provisioning preflight, claim, retry, stale recovery, ready, unmanaged,
    and failure settlements drained by the existing provider-control Worker.
- Non-goals:
  - final Discord title GET/PATCH reconciliation;
  - lifecycle terminalization for archive, disconnect, decommission, connection
    termination, restore, or purge;
  - deterministic testenv fake changes or product E2E;
  - Living Spec promotion;
  - an execution gate, new outbox, Redis authority, broker mode, feature flag,
    compatibility fallback, or legacy delivery-enum change.
- Interfaces:
  - provider-neutral history returns canonical messages plus an optional typed
    Discord root-thread observation; Slack returns no Discord observation;
  - `thread_absent` requires the exact root response to contain no thread object and
    no thread-present flag; malformed, incomplete, inconsistent, or mismatched
    evidence is `unknown`;
  - the title-artifact service accepts exact Session, creating Binding, Resource,
    trigger provider-message key, provisional title, access-request provenance when
    applicable, and Discord observation; retries with incompatible immutable
    provenance fail;
  - Access-Allow-created Session/Binding artifacts are attached during the exact
    replay even when replay reports `session_created = false`;
  - projection creation and mailbox acceptance share the admission transaction, and
    no provisioning readiness is awaited before commit or wake;
  - current ordinary `ensure_thread()` uses the stored projection provisional title
    when a matching projection exists, while legacy rows and Workers remain valid;
  - projection reconciliation GETs first, persists preflight absence before POST,
    never blindly replays an ambiguous POST, and re-GETs for recovery;
  - direct proof requires a projection-owned persisted preflight/attempt plus a valid
    successful response or GET reconciliation proving the active Bot owner and exact
    stored provisional title;
  - adoption additionally requires exact admission absence, Guild/parent/root
    identity, canonical-target consistency, complete owner/name/thread metadata
    including creation timestamp, and current connection/route/Resource/Binding/
    Session/Agent/credential authority;
  - incomplete or conflicting evidence may preserve the usable Resource target but
    cannot establish title ownership;
  - the existing provider-control loop claims bounded projection work directly from
    the projection repository; no projection row enters legacy delivery readers.
- Approved Design mechanisms: `M1`, `M2`, `M4`, `M5`, `M8`
- Authority references:
  `title-260802/REQ-1`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`;
  `title-260802/ADR-D1`, `ADR-D3`, `ADR-D4`, `ADR-D6`;
  `title-260802/DESIGN` revision `5`
- Design delta: `None`
- Removal obligations:
  - replace independent new-Session/Binding creation paths with the shared
    title-artifact boundary for this feature;
  - remove title-ownership inference from Resource labels, delivery status, Bot
    ownership alone, current Agent name, or incomplete provider metadata;
  - replace projection-owned provider mutation followed by unfenced local recording
    with persisted preflight and atomic readiness settlement;
  - preserve ordinary legacy `ensure_thread()` as usable delivery behavior without
    treating it as title authority.
- Absence verification:
  - production call-site audit proves both root-Session creation paths invoke the
    artifact service and no unrelated path creates candidates;
  - tests prove label/status/Bot-only/current-Agent-name evidence cannot produce
    provider readiness;
  - actual legacy delivery readers and enum tables remain unchanged;
  - grep and behavior tests show no title PATCH, execution gate, outbox, broker mode,
    new configuration, API, frontend, or lifecycle behavior in this phase.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Artifact creation and persistence settlements | `/root/title-persistence-owner` | additive provenance migration/revision; `rdb/models/external_channel.py`; `repos/external_channel/{data.py,title.py}`; new title-artifact service; `services/external_channel/{ingestion.py,mailbox_ingestion_store.py,access.py,ingestion_replay.py}`; focused repository/ingestion/access tests | Phase 1 schema and fixed observation/provisional-title contracts | Shared idempotent artifact creation, both producer paths, exact provisioning preflight and settlement mutations | Repository DB tests; ingestion-store, replay, and Access-Allow tests |
| Discord observation, proof, and Worker integration | `/root/title-runtime-owner` | `services/external_channel/conversation.py`; `discord_history.py`; `ingestion_history.py`; `discord_delivery.py`; `channel_action.py`; `provider_control.py`; new Discord projection reconciliation service; focused history/delivery/action/Worker tests | Fixed artifact and repository interfaces | Fail-closed observation, candidate-aware ordinary provisioning, direct/adopted proof, bounded Worker drain | Discord history/delivery/projection/provider-control tests; mixed-version reader checks |
| Plans and integration | `/root` | phase plan, shared dependency composition, cross-workstream test fixtures, branch/PR metadata | Both workstreams | Integrated Phase 2 diff, scope audit, final validation, PR | Combined Ruff, Pyright, focused Pytest, diff and producer/legacy-reader audits |
| Independent review | `/root/title-feature-reviewer` | Read-only complete Phase 2 diff | Stable implementation and evidence | Prioritized findings or PASS | Review against M1/M2/M4/M5/M8, D6 non-blocking execution, provider-proof safety, and phase boundaries |

- Integration order:
  1. Runtime owner defines the typed Discord observation and provider read/create
     result consumed by the artifact and reconciliation services.
  2. Persistence owner adds repository settlement contracts and the shared artifact
     boundary, then wires ordinary ingestion and Access-Allow replay.
  3. Runtime owner implements candidate-aware ordinary provisioning, direct/adoption
     proof, and the existing Worker-loop drain against the stable repository
     interface.
  4. Both owners add focused race, crash, mixed-version, existing-thread,
     Agent-rename, and no-wake-gate tests within their owned paths.
  5. Primary orchestrator integrates shared dependency composition and runs combined
     validation and bidirectional scope-drift checks.
  6. Each owner requests read-only review from `/root/title-feature-reviewer`.
  7. Required corrections are applied in one pass; targeted re-review is requested
     only for Requirements/Design, security/data-loss, or material interface changes.
- Independent review:
  - Scope: complete Phase 2 diff against `title-260802/REQ-1`, `REQ-3`, `REQ-4`,
    `REQ-5`, `REQ-6`, ADR D1/D3/D4/D6, M1/M2/M4/M5/M8, and this phase contract.
  - Criteria: exact admission observation, complete creation-path coverage,
    immediate unchanged execution, no ambiguous POST replay, exact direct/adoption
    proof, conservative unmanaged fallback, candidate provisional-name authority,
    current lifecycle/credential validation, persisted retry/stale recovery, and
    legacy-reader isolation.
  - Inputs: Requirements, ADR, approved Design revision 5, current Specs, PR #1093,
    this plan, implementation diff, and validation evidence.
  - Output: grounded Critical/Warning findings or explicit PASS.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - focused title repository, ingestion store/history/replay, Access-Allow, Discord
    history/delivery/action/projection, and provider-control Pytest
  - production candidate-producer and legacy-reader grep audits
  - `python -m pytest scripts/tests/test_gen_docs_index.py`
  - pre-commit snapshot/frontmatter/index validation during commit
  - `git diff --check`
- Validation evidence:
  - Ruff format and check passed for all 31 changed Python files.
  - Full backend Pyright passed with `0 errors, 0 warnings`.
  - Primary integrated Phase 2 matrix passed: `147 passed`; the only warnings were
    three existing testcontainers deprecation warnings.
  - Runtime expanded focused validation passed: `135 passed`.
  - Persistence/provenance focused validation passed: `61 passed`.
  - Independent final review reran a broader changed-surface matrix:
    `180 passed`, with the same three existing warnings.
  - A fresh isolated PostgreSQL validated
    `fc4b83f4fe17 -> 7e425e8e3b7b`, empty downgrade and re-upgrade, and the
    state-written admission-provenance downgrade guard. The Phase 1 migration was
    not modified, and the temporary database container was removed.
  - The first runtime review found three Critical and two Warning issues; all were
    corrected and targeted runtime re-review reported PASS.
  - The first persistence/producer review found three Critical and one Warning
    issue; all were corrected with the additive provenance migration, durable final
    authority fence, and integration tests.
  - Final independent complete-diff review reported PASS with no remaining
    correctness, data-integrity, authority, ambiguous-POST, DI, or migration finding.
- Scope-drift check:
  - verify every Phase 2 outcome and removal obligation is implemented;
  - verify Session execution and ordinary delivery are never gated by projection
    readiness;
  - verify no title PATCH, lifecycle integration, testenv E2E, Spec promotion,
    outbox, mailbox gate, broker/config/API/frontend change, or fallback was added;
  - return any new material mechanism to feature design.
- Context checkpoint:
  - Discord history now carries a required nullable credential-free exact-root
    observation. Missing or inconsistent thread flags, identity, Guild, ownership,
    name, or creation metadata fail closed.
  - Ordinary new-Session admission and Access-Allow use one idempotent artifact
    service. Candidate admission provenance retains the exact Access request and
    admission-time provisional Agent title through replay.
  - Additive migration `7e425e8e3b7b` extends the candidate without modifying the
    Phase 1 migration `fc4b83f4fe17`.
  - Candidate-aware current ordinary delivery reads the matching projection and uses
    its stored provisional title. A projection mismatch causes no provider mutation;
    a no-projection old-producer row retains legacy Agent-name `ensure_thread()`.
  - GET-first projection reconciliation persists preflight before POST, recovers an
    ambiguous or interrupted create by GET without blind replay, and establishes
    only complete direct or admission-evidence adoption proof.
  - Final settlement locks and revalidates projection, Resource, Binding, candidate,
    Session, route, Agent, and connection. Canonical target conflict becomes
    unmanaged/relinquished while preserving the existing target; authority loss
    becomes failed/relinquished.
  - The existing provider-control Worker drains bounded projection provisioning
    claims. Mailbox admission, running transition, commit, wake, Agent execution, and
    ordinary at-most-once delivery remain independent from projection readiness.
  - Phase 3 still owns final title GET/PATCH reconciliation and lifecycle
    terminalization. Design delta: `None`.
