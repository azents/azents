---
title: "Agent Deletion Phase 1: Participants and Ownership"
created: 2026-10-20
tags: [agent, lifecycle, backend, testing]
---

# Phase Execution Plan

- Phase: 1 of 4, participants and ownership.
- Branch/base: `feat/agent-deletion-participants` → `design/agent-deletion-lifecycle`.
- PR boundary: independently testable deletion responsibilities and registry-owned finalization.
- Inputs: approved `harbor-261020` Design revision 2 M1–M12; emergency fix #2356 and backend convention #2357.
- Approved mechanisms: M1–M9; authority REQ1–7 and ADR-D1–D3.
- Design delta: None.
- Non-goals: public deletion status, user-mutation read-only guard, new failure column, comprehensive later-phase matrices, or new E2E scenarios.
- Removal obligations: old monolithic cleanup sequencing and finalizer manual model/absence tuples; unfenced Agent-owned stop/blob/final-cleanup writes.
- Absence verification: search replaced call sites and compare registry handlers/verification exactly; migrated PostgreSQL catalog coverage.

| Workstream | Owner | Paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Domain contracts and registry | /root | core/agent_deletion*, services/agent_decommission*, services/agent_deletion* | Existing domain cleanup contracts | Immutable context/definitions/evidence, deterministic dependencies and attributable failures | Pure contract tests and existing coordinator tests |
| DB fencing and finalization | /root | repos/agent_decommission*, repos/agent_deletion* | Domain contracts | Same-transaction job/Agent/owner/attempt guard; registry-owned checks/cleanup; exact avatar evidence | Existing lease/finalizer tests, baseline PostgreSQL checks |
| Schema facts and ownership | /root | core/session_lifecycle_schema.py, repos/session_lifecycle_schema.py, core/agent_deletion*, services/agent_deletion* | Existing neutral catalog query | Ordered columns, scoped incoming-edge coverage, no Session execution change | Migrated PostgreSQL catalog and existing Session schema suite |
| Current spec evidence | /root | docs/azents/spec/domain/agent.md and focused deletion dependency section | Verified code/catalog | Resource keys, relationships/delete actions, cleanup/preservation owner | Docs validator and evidence diff |

Integration order: contracts/catalog → completed operations and verification → participants/coordinator → existing test adaptation and baseline checks → current spec. All new fields are explicit. No external I/O inside DB transactions. Agent scoped failures must not erase shared or historical state.

Independent review: `/root/deletion-fix-review`, read-only review requested by root after integrated checks. Root alone applies corrections and reruns validation.

Final validation: Ruff/format, whole-backend ty, focused decommission/owner-retirement/Runtime/schema pytest suites, migration model/DDL alignment, docs validation and commit hooks, then latest-SHA CI.

## Integrated Checkpoint

Completed the six participant contracts, exact attempt/avatar evidence, registry-derived finalization, full column-scoped root/cascade catalog, and fenced stop/blob/cleanup operations. Removed the old monolithic cleanup helper and finalizer's independent table tuples. The former fixed Agent-FK test now retains only Workspace-parent ownership checks; full Agent edge coverage is tested from the migrated catalog.

Root validation: changed-file Ruff/format passed; whole-backend `uv run ty check --error-on-warning` passed; 35 focused tests passed (actual PostgreSQL leases/finalization/owner retirement/catalog, coordinator and Agent API data); migration single-head/model-DDL checks 2 passed; docs validator and diff check passed. An initial duplicate SQL TableClause identity failure was corrected with per-verifier table identity reuse and all affected tests rerun successfully.

Independent reviewer `/root/deletion-fix-review` found no Critical/Warning/Suggestion issues in the stable integrated diff. Design delta: None. Broader test matrices, typed normal waits/error presentation, and user read-only guards remain their approved later phases. Next: open phase-1 PR and branch phase 2 from its commit; track every latest-SHA CI before overall completion.
