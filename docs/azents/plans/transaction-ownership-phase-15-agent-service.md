---
title: "Transaction Ownership Phase 15: Agent Service Operations"
created: 2026-10-01
tags: [backend, agent, architecture, database]
---

# Phase Execution Plan

- Phase: `15, Agent service completed operations`
- Branch/base: `refactor/transaction-ownership-261001-3-agent-services` → `refactor/transaction-ownership-261001-2-engine-reads`
- PR boundary: replace the database transaction contexts owned by `services/agent/__init__.py` with typed completed Agent-domain repository operations, including the runtime-profile availability predicate needed by create and update.
- Inputs: Phase 14 Engine operations and the approved `transaction-260908` Requirements, ADR, and Design revision 1.
- Deliverables: completed Agent settings, create/update/decommission, visibility/admin, and avatar database operations; database-only runtime-profile availability composition reusable by Agent operations; unchanged external projection and publication ordering.
- Non-goals: Agent API or data-model changes, Runtime Profile product policy, upload/S3 behavior, terminal invalidation semantics, model catalog behavior, retry/fallback changes, schema/configuration changes, or cross-I/O locks.
- Interfaces: existing Agent service `Result` errors, optimistic runtime-profile selection version fence, Agent lifecycle/Workspace authorization, first-admin creation, stale Session inference-profile reconciliation, decommission atomicity, admin-count protection, avatar cleanup ownership, and terminal-policy invalidation order remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove Agent service-owned transaction contexts and the session-taking Runtime Profile availability helper from the Agent mutation path; replace them with repository-owned database-only operations.
- Absence verification: search `services/agent/__init__.py` for direct session-manager contexts, verify new repository modules import no services or external collaborators, and verify upload, S3, model catalog, Runtime projection, and invalidation publisher work occurs only after completed repository operations.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runtime Profile availability composition | `/root` | `repos/runtime_profile/**`, bounded `services/runtime_profile_workspace/**` callers and tests | Existing profile/provider/policy/control repositories | Database-only availability predicate callable inside Agent atomic operations | Runtime Profile focused tests; no service imports from repository code |
| Agent completed operations | `/root` | `repos/agent_operations.py`, tests | Existing Agent/admin/Workspace/Session/decommission/retention repositories and availability composition | Typed complete read/write operations preserving current atomic groups and fences | Repository transaction-closure, rollback, and outcome tests |
| Agent service orchestration | `/root` | `services/agent/__init__.py`, focused tests, related Agent Spec paths | Both repository workstreams | External model/upload/S3/projection/publication work sequenced around completed DB operations | Agent service tests; direct-session absence search; Spec review |

- Integration order: extract the database-only availability composition, implement Agent completed operations, rewire service methods in behavior-preserving groups, update focused tests and Spec paths, then run integrated validation.
- Independent review: `/root/issue-hardening-review` performs one read-only review after all implementation workstreams are complete and the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, Runtime Profile and Agent service/repository focused pytest, pre-commit, transaction/import searches, and creates the stacked PR.
- Scope-drift check: confirm every Agent service DB context is assigned or explicitly deferred with evidence, all existing authorization/atomicity/error behavior remains represented, and no new lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism is added.
- Context checkpoint: PR #2005 is green and PR #2006 is open as the preceding stack. Phase 15 owns `services/agent/__init__.py`; broader Agent Runtime, Agent Session input, decommission worker, Chat Workspace, Discord settings, idle continuation, and residual entrypoints remain for later stack phases unless a direct dependency is required for this bounded extraction.
