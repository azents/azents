---
title: "Agent Vault Phase 1: Storage"
created: 2026-11-28
tags: [vault, agent, security]
---

## Phase Execution Plan

- Phase: `1/3` — Agent-owned storage.
- Branch/base: `feat/agent-vault-storage` → `main`.
- PR boundary: additive PostgreSQL storage, lifecycle registry, encrypted entry repository and its permissions; no public writer, tool, or UI yet.
- Inputs: [implementation plan](agent-vault-implementation-plan.md), [Design v1](../design/vault-261127-agent-vault.md), current cipher and Agent lifecycle.
- Deliverables: per-entry storage using existing encryption, manager-visible metadata operations, application-internal resolution, filesystem intake and batch composition seams for later phases, and lifecycle tests.
- Non-goals: settings routes/UI, Runtime calls or protocols, requests, migrations of Runtime values, data readback APIs, rotation or a new key.
- Interfaces: Agent-scoped repository accepts explicit name and mutation intent, returns names/contributor metadata for management, and allows internal lookup of selected values. Transaction composition supports an authorized caller's atomic batch.
- Approved Design mechanisms: `M1`, `M2`, `M11`, `M12` (storage slice).
- Authority references: REQ-1, REQ-3, REQ-5; ADR-D1, ADR-D2, ADR-D4 (composition boundary only); [Agent deletion](../spec/domain/agent-deletion.md), Design v1.
- Design delta: `None`.
- Removal obligations: none.
- Absence verification: repository metadata reads exclude ciphertext and do not decrypt; preserve existing Agent Runtime environment and credential configuration.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema and lifecycle | Primary agent | Azents `rdb/models`, generated `db-schemas/rdb` revision, Agent deletion registry | Agent schema and migration head | Unique `(agent_id, name)` and explicit deletion ownership | Migrate isolated PostgreSQL and run catalog/constraint tests |
| Entry storage and management policy | Primary agent | Azents `repos/agent_vault*` and focused tests | Schema and credential cipher | Authorized metadata, explicit writes, selected internal lookup and batch compose | Repository integration tests with alternate Agent/Workspace and synthetic values |
| Spec and approval baseline | Primary agent | Vault snapshot and owning Spec Wiki page | Verified model and lifecycle behavior | Exact revision approval and current storage schema facts | Document validator, link check and scope audit |

- Integration order: migration/catalog → repository and tests → verified schema Spec Wiki.
- Independent review: `vault-reviewer`; primary agent requests review on the frozen integrated diff.
- Final validation: targeted Ruff and ty, pytest with an isolated migrated PostgreSQL, migration head and document validation.
- Scope-drift check: no registered writers or new Runtime/default behavior, no private keys or plaintext in persisted records.
- Context checkpoint: Storage schema and repository implemented on `main` baseline `f15373240`. Migrated PostgreSQL 17, 17 pytest checks (including membership revocation and FK compatibility), focused Ruff/ty and document validation passed. Independent review and targeted re-review closed the grant and lock-order findings. Phase 2 consumes this reviewed storage boundary after the Phase 1 PR is open.
