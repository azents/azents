---
title: "LLM Backend Phase 1: Shared Contracts"
created: 2026-10-28
tags: [engine, inference, security]
---

# Phase Execution Plan

- Phase: 1/4, shared contracts and approved authority snapshot.
- Branch/base: `feat/relay-contracts` -> `main` (`3792f3fc`).
- PR boundary: new independent shared package, deterministic target identity, closed authority DTOs, contract CI, confirmed design artifacts.
- Inputs: [Requirements](../requirements/relay-261028-model-inference.md), [ADR](../adr/relay-261028-model-inference.md), approved [Design r1](../design/relay-261028-model-inference.md).
- Deliverables: importable shared contracts with no Azents app or LiteLLM dependency; stable target IDs; typed secret-safe provider bindings; focused validation.
- Non-goals: database migrations, routes, Proxy deployment, Worker changes, premium-option policies, compatibility fork.
- Interfaces: internal model-list/resolve requests and responses, closed credential variants, pure target derivation. Requester-visible wire remains LiteLLM Responses; no new inference protocol.
- Approved Design mechanisms: M2, M3, M6, M7, M9, M16 (shared contract portions only).
- Authority references: relay-261028/ADR-D2, D3, D6, D7; relay-261028/REQ-2, REQ-3, REQ-5.
- Design delta: None.
- Removal obligations: None for current Worker/state; the new package replaces no existing authoritative unit.
- Absence verification: no app import/dependency; no target registry, token UI, Worker route mutation, deployment or credentials.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared contracts | Primary | `python/libs/azents-llm-contract/**` | Approved r1 | identity, DTOs, typed credential variants | Ruff, ty, pytest, secret serialization |
| Contract CI | Primary | `.github/workflows/ci.yaml`, `.pre-commit-config.yaml` | Package | package included in checks | YAML parse, existing CI structure |
| Documentation | Primary | snapshot docs and these plans | Confirmed discussion | approval and phase boundary | docs catalog + references |

- Integration order: contract package -> focused tests -> CI wiring -> stable diff review -> commit/PR/CI.
- Independent review: `/root/relay-reviewer`; primary requests after root validation, applies all corrections.
- Final validation: root runs UV lock/sync, Ruff format/check, ty, pytest, docs catalog, diff check.
- Scope-drift check: no independent mapping/config source, no token/provider secrets exposed in ordinary representations; secret values serialize only via an explicitly named wire method for the protected channel.
- Context checkpoint: not started; server persistence/issuer/authority next, then actual Proxy. Conditional provider compatibility remedies remain later acceptance work, not hidden scope in this phase.
