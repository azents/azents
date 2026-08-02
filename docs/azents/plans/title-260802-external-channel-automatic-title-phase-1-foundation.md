---
title: "External Channel Automatic Title Phase 1 Foundation Execution Plan"
created: 2026-08-02
updated: 2026-08-02
tags: [external-channel, session, discord, title, backend, database]
---

# Phase Execution Plan

- Phase: `1 — Persistence foundation`
- Branch/base: `azents/roast-inherit-few` → `main`
- PR boundary: Land the approved snapshot, generated additive schema, durable
  Session-title candidate and Discord projection repository contracts, and
  candidate-gated External Channel title-source support without activating candidate
  production.
- Inputs:
  - confirmed `title-260802/REQ`;
  - accepted `title-260802/ADR-D1` through `ADR-D6`;
  - approved `title-260802/DESIGN` revision `5`;
  - current External Channel and Session title Specs and code;
  - repository migration and Python conventions.
- Deliverables:
  - generated additive RDB migration and revision pointer;
  - typed candidate/projection enums, models, constraints, and explicit indexes;
  - repository data and mutation contracts for idempotent artifact creation,
    candidate consumption, projection state, due claims, stale recovery, and atomic
    final-title arming;
  - closed authorized External Channel title extractor with safe body/file metadata;
  - candidate-gated initial automatic title assignment preserving manual precedence;
  - focused tests proving no current producer activates the feature in this phase.
- Non-goals:
  - Discord root observation parsing;
  - ingestion or Access-Allow candidate production;
  - provider provisioning, adoption, title GET/PATCH, or Worker drain;
  - lifecycle integration beyond schema/repository ownership prerequisites;
  - testenv E2E, Living Spec promotion, deployment, or live provider mutation.
- Interfaces:
  - one candidate is unique per new External Channel AgentSession and immutably owns
    creating Binding plus exact trigger provider-message key;
  - candidate states are `pending`, `consumed`, or `relinquished`;
  - one Discord projection is unique per eligible Resource and references the durable
    candidate, creating Binding/Session, stored provisional title, observation fields,
    provisioning/title phases, retry timing, claims, and sanitized failures;
  - no new enum or row is added to `external_channel_delivery_attempts`;
  - `initial_title_from_event()` remains closed: direct `user_message` is eligible as
    today; `external_channel_message` is eligible only with human
    `authorized_invocation` payload and a matching pending candidate;
  - Session title columns remain the only Session-title authority;
  - successful final automatic-title replacement can atomically arm matching
    projections through a repository contract, but provider reconciliation is not
    executed in this phase.
- Approved Design mechanisms: `M1`, `M2`, persistence prerequisites for `M3`–`M8`
- Authority references:
  `title-260802/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-6`;
  `title-260802/ADR-D1`, `ADR-D2`, `ADR-D4`, `ADR-D6`;
  `title-260802/DESIGN` revision `5`
- Design delta: `None`
- Removal obligations:
  - replace `USER_MESSAGE`-only automatic-title extraction with the approved closed
    user-like extractor;
  - prevent `title_source = null` or a later External Channel Event from creating
    eligibility without the durable candidate;
  - keep projection authority out of Resource labels and legacy delivery enums.
- Absence verification:
  - tests show an External Channel Event without the exact candidate remains
    ineligible;
  - later Events and later Bindings cannot consume the candidate;
  - schema and grep checks show no projection fields in Resource labels and no new
    legacy delivery enum values;
  - production candidate creation call sites remain absent until Phase 2.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Migration and RDB models | `/root/title-persistence-owner` | `python/apps/azents/db-schemas/rdb/**`, `python/apps/azents/src/azents/rdb/models/external_channel.py`, focused model tests | Approved persistence model | Generated migration, revision pointer, typed tables/constraints/indexes | Migration/model tests, schema inspection |
| Repository contracts | `/root/title-persistence-owner` | new/changed `python/apps/azents/src/azents/repos/external_channel/**`, focused repository tests | RDB models | Candidate/projection data, create/consume/claim/arm mutations | Focused repository Pytest |
| Session title integration | `/root/title-runtime-owner` | `python/apps/azents/src/azents/services/session_title.py`, `python/apps/azents/src/azents/repos/agent_session/**`, mailbox title-assignment boundary and focused tests | Candidate repository contract | Closed External Channel extractor and candidate-gated initial/final title contracts | Session title, mailbox, agent-session repository tests |
| Plans and integration | `/root` | snapshot docs, implementation/phase plan, shared dependency wiring, branch/PR metadata | All workstreams | Integrated Phase 1 diff and validation | Scope audit, combined checks |
| Independent review | `/root/title-feature-reviewer` | Read-only complete Phase 1 diff | Stable implementation and evidence | Prioritized findings or PASS | Review against M1/M2 and phase contract |

- Integration order:
  1. Generate the migration and define model/data contracts.
  2. Implement candidate/projection repository mutations and focused persistence
     tests.
  3. Integrate the closed title extractor and candidate-gated title assignment.
  4. Run focused checks, verify candidate production remains unwired, and integrate
     snapshot/plan documentation.
  5. Each implementation owner requests read-only review from
     `/root/title-feature-reviewer`.
  6. Apply required findings in one batch, rerun affected checks, and request targeted
     re-review only for requirements/design, security/data-loss, or material
     interface corrections.
- Independent review:
  - Scope: complete Phase 1 diff against `title-260802/REQ-1`, `REQ-2`, `REQ-3`,
    `REQ-4`, `REQ-6`, M1/M2, approved persistence prerequisites, and this phase plan.
  - Criteria: generated migration only, correct restrictive ownership, typed enums,
    exact candidate identity, no mailbox-row FK, no label/legacy-ledger authority,
    preserved manual title precedence, no accidental producer activation, and
    deterministic focused tests.
  - Inputs: Requirements, ADR, approved Design revision 5, current Specs, this phase
    plan, implementation diff, and validation results.
  - Output: grounded Critical/Warning findings or explicit PASS.
- Final validation:
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - focused migration/model/repository/Session-title/mailbox Pytest
  - `python -m pytest scripts/tests/test_gen_docs_index.py`
  - pre-commit snapshot/frontmatter/index validation during commit
  - `git diff --check`
- Validation evidence:
  - Ruff format and check passed for all 15 changed Python files.
  - Full backend Pyright passed with `0 errors, 0 warnings`.
  - Integrated changed-test suite passed: `145 passed`; the only warnings were three
    existing testcontainers deprecation warnings.
  - Direct repository coverage passed: `8 passed`, including idempotent creation,
    exact consume/relinquish fences, trigger-provenance FK rejection, title arming,
    runnable-title DB rejection, due claims, and stale recovery.
  - A fresh isolated PostgreSQL validated upgrade from `772e7ab22a8e` to
    `fc4b83f4fe17`, empty-state downgrade and re-upgrade, and the state-written
    downgrade guard. The temporary container was stopped.
  - Documentation index tests passed: `14 passed`.
  - `git diff --check` passed.
  - Runtime independent review passed without findings. Persistence review found one
    Critical and two Warning issues; all were corrected, and the same reviewer
    reported PASS on targeted re-review.
- Scope-drift check:
  - verify M1/M2 foundation and approved prerequisites are complete;
  - verify no candidate producer, Discord provider mutation, Worker drain, outbox,
    mailbox gate, broker mode, frontend/API/config change, or fallback was added;
  - any new material state or runtime behavior returns to feature design.
- Context checkpoint:
  - Added candidate and Discord projection tables with five PostgreSQL enum types,
    restrictive ownership constraints, explicit due indexes, and migration revision
    `fc4b83f4fe17`.
  - Added idempotent create, exact consume/relinquish, atomic title arming, due claim,
    and stale recovery repository contracts.
  - External Channel title extraction now accepts only human
    `authorized_invocation` Events and uses bounded body, file-name, and media-type
    metadata.
  - Mailbox promotion requires the exact pending Session/Binding/trigger candidate,
    terminalizes it on every matching outcome, and preserves the existing direct
    `user_message` behavior and manual-title precedence.
  - Final generated-title replacement arms matching projections in the same
    transaction, but no provider reconciler runs in this phase.
  - Production candidate and projection creation call sites remain absent. Phase 2
    owns admission observation, both artifact-creation paths, provider proof, and
    Worker reconciliation.
  - Design delta: `None`; no unauthorized execution gate, outbox, broker mode,
    provider mutation, API, frontend, configuration, or compatibility fallback was
    introduced.
