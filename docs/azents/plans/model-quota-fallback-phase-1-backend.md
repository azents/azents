---
title: "Model Quota Fallback Phase 1 Backend Vertical Slice"
created: 2026-09-12
updated: 2026-09-12
tags: [models, agent, api, migration, engine, implementation]
---

# Model Quota Fallback Phase 1 Backend Vertical Slice

## Phase Execution Plan

- Phase: `1/2 Backend vertical slice`
- Branch/base: `feat/model-quota-fallback-1-backend` → `design/model-quota-fallback-260912`
- PR boundary: complete persisted, public, and runtime backend behavior for quota-triggered model fallback
- Inputs: confirmed `model-260912/REQ-1` through `REQ-8`, accepted `ADR-D1` through `ADR-D7`, approved `model-260912/DESIGN` revision 2
- Deliverables: nested candidate configuration; coordinated migration and write fence; strict public v1
  and generated clients; AgentRun, Session, title, candidate-health, probe and reservation state;
  foreground, compaction and title quota progression; availability/reserve/cancel API; route
  provenance, diagnostics, telemetry; deterministic provider controls and backend evidence
- Non-goals: final nested settings editor, Composer/picker/Drawer recovery presentation, Storybook
  completion, browser E2E, Living Spec promotion, release publication, deployment, merge
- Interfaces: `label + candidates[]`, one-to-five ordered candidates, Primary-derived internal mirrors,
  semantic label intent, `quota_or_billing` progression before generic retry, five-minute
  PostgreSQL cooldown, single foreground half-open claim, one-shot root Session Primary reservation,
  DB-derived availability, bounded actual-route provenance
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9`, backend portions of `M10` and `M11`, retained boundary `M12`
- Authority references: `model-260912/REQ-1` through `REQ-8`; `ADR-D1` through `ADR-D7`; current Agent, Model Catalog, Conversation, Execution Loop, Run Resume, and Context Compaction Specs
- Design delta: `None`
- Removal obligations: singular option shape and public mirrors/inputs; compatibility decoders;
  outer-only checks; Session-only routing authority; undifferentiated quota retry; same-model-only
  compaction/title quota handling; live/session contract without availability/reservation; turn
  provenance without actual candidate route
- Absence verification: strict backend and tRPC ingress tests, OpenAPI/generated-client inspection,
  repository search, migration transform and downgrade-fence tests, retry/provider journals,
  restart/concurrency tests, and bounded schema assertions

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Configuration and public contract | `/root` | core Agent types, Agent/Workspace services/repos/APIs, OpenAPI and clients | M1-M3/M5 | canonical nested config and strict clean cutover | core/service/API tests, generation and compile |
| Database authority | `/root` | Alembic revision, AgentRun/Session/candidate-health/cutover RDB models and repositories | M2/M4/M7/M8 | operation state, cooldown/claims, reservation/title state, rollback fence | migration/schema/CAS tests |
| Candidate selection and foreground execution | `/root` | inference resolution, Run repositories/controller/executor | M4-M7/M9/M12 | frozen chains, compatibility/cooldown skips, quota-before-retry and provenance | focused engine/worker/recovery tests |
| Background operations | `/root` | compaction and Session title services/repositories | M4/M6/M7/M9/M12 | independent Lightweight chains and shared cooldown updates | compaction/title retry and race tests |
| Session recovery API | `/root` | Session repositories/services, chat v1/live data and routes | M7-M10 | DB-derived availability plus reserve/cancel/transfer | authorization, conflict, deadline and live tests |
| Deterministic backend substrate | `/root` | AIMock/provider fixture, backend test controls and journal/barriers | M11 | credential-free scripted candidate evidence | focused fixture and backend E2E-support tests |
| Independent review | `/root/design-code-review` | read-only complete phase diff | stable phase diff and evidence | material findings only | authority, concurrency, recovery, security, data integrity, removal audit |

- Integration order: canonical config → complete migration/write fence → public contract/clients →
  typed operation and health repositories → selection/compatibility → foreground progression →
  compaction/title → reservation/availability → provenance/telemetry → deterministic evidence → review
- Independent review: `/root/design-code-review` reviews Requirements, ADR, Design revision 2,
  M1-M12 coverage owned by this phase, rollback fencing, external-I/O transaction boundaries,
  concurrency generations, Stop/retry preservation, strict clean-cutover absence, data safety, and
  validation evidence
- Final validation: full affected Python Ruff/format/ty/pytest; migration upgrade/downgrade/data and
  schema checks; OpenAPI plus Python/TypeScript client generation; forced Web typecheck for the new
  public contract; deterministic backend matrix; docs index hook; `git diff --check`; required CI
- Scope-drift check: every hunk traces to backend mechanisms M1-M9, required generated/current callers,
  backend support for M10/M11, or M12 preservation; no visual redesign, browser-only behavior,
  feature flag, compatibility alias, alternate authority, synthetic probe, or label fallback
- Context checkpoint: Design revision 2 is approved; initial review identified and correction now
  includes strict tRPC ingress, complete M2 schema foundation, and durable post-write downgrade fence;
  phase 2 owns the final Web recovery presentation, credential-free browser E2E, Specs, and cleanup
