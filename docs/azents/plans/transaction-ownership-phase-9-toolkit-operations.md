---
title: "Transaction Ownership Phase 9: Toolkit Operations"
created: 2026-09-08
tags: [backend, architecture, database, toolkit, oauth]
---

# Phase Execution Plan

- Phase: 9, Toolkit operation repository ownership and external validation separation.
- Branch/base: `refactor/toolkit-operations-transactions-260908` →
  `refactor/project-mailbox-transactions-260908` at `54df1393e342ca9945aa79489548b8f8b6e312f4`.
- PR boundary: remove every application-owned database lifetime from Toolkit CRUD,
  scope management, Agent attachment, and response OAuth composition while
  preserving the current Public API contract and credential behavior.
- Inputs: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md),
  [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md),
  [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md)
  revision 1, the model/integrations transaction audit and its 136 database
  context entries plus one VFS lock observation, Phase 2 Project/Mailbox and
  Toolkit State repository patterns, and the current Toolkit Living Spec.
- Deliverables: completed typed Toolkit operation repository calls; atomic
  Toolkit-plus-workspace-scope creation; database-only MCP OAuth summary
  composition; external credential and Platform GitHub App resolution outside
  database transactions; final workspace, Toolkit, provider type, platform App,
  user installation, scope, Agent, membership, availability, and attachment
  authority revalidation at each mutation.
- Non-goals: public API or schema changes, migrations, provider protocol changes,
  new retries, locks, fallbacks, live infrastructure work, generic transaction
  callbacks, live session aliases, repository-to-service imports, or Engine tool
  changes beyond the imports and direct callers required by the fixed service
  contract.
- Interfaces: `ToolkitService` orchestrates pure validation and external settings
  resolution around detached repository snapshots; a Toolkit operation repository
  owns all sessions and composes the existing Toolkit, scope, AgentToolkit,
  Agent, workspace-user, GitHub installation, and MCP OAuth query repositories;
  narrow repositories retain database-only in-session primitives for composition.
- Approved Design mechanisms: M1, M2, M3, M4, M5.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`,
  `transaction-260908/ADR-D1` through `ADR-D3`, Design revision 1, and the current
  Toolkit Spec.
- Design delta: None.
- Removal obligations: remove `SessionManager` and SQLAlchemy imports from
  `ToolkitService`; remove service-owned contexts and nested OAuth/settings
  resolution from the Toolkit create/update/read paths; replace split authority
  checks followed by unguarded mutations with bounded repository compositions.
- Absence verification: search the Toolkit service for transaction factories and
  SQLAlchemy imports; search operation repositories for service imports or generic
  callbacks; enumerate every audit-listed Toolkit context and report any residual.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| M1 repository operations | `/root` | `python/apps/azents/src/azents/repos/toolkit*/**`, directly required narrow repository data/tests | Phase 2 repository pattern | Typed completed CRUD, scope, OAuth summary, and Agent attachment operations | Repository unit/integration tests, rollback assertions, caller search |
| M2 service orchestration | `/root` | `python/apps/azents/src/azents/services/toolkit/**` | M1 | No service-owned transaction; external Platform/settings and provider validation see zero active transaction | Service boundary tests and transaction probes |
| M3 final authority | `/root` | Toolkit operation repository and directly required GitHub installation/settings data access | M1, M2 | Exact workspace/Toolkit/provider/platform/user/Agent authority is revalidated in final mutation transactions without adding locks | Stale workspace, deleted Toolkit, reconnect/App drift, and update race tests |
| M4 integration | `/root` | direct FastAPI/Worker/API/MCP OAuth DI callers and tests only | M1–M3 | Constructor graph and OAuth projection use completed operations without API drift | Focused and full affected Pytest, Ruff, format, ty |
| M5 evidence/spec | `/root` | `docs/azents/spec/domain/toolkit.md`, this plan | M1–M4 | Updated date/version/changelog, residual context and lock ledger (`none` unless evidence changes) | Spec validation, staged pre-commit, independent review |

- Integration order: add operation data contracts; implement repository-owned reads
  and mutations; convert Toolkit service orchestration; update direct dependency
  construction and MCP OAuth summary composition; add deterministic regression
  tests; update the Toolkit Spec; run the validation matrix; perform direct
  review as requested and apply material corrections.
- Direct review: `/root`, review against the Requirements, ADR, Design revision 1,
  this phase contract, the stable diff, and validation evidence. No subagents are
  used. The review must check authorization and credential semantics, atomic
  rollback, stale-authority rejection, DB/external separation, layering, and the
  absence of unauthorized compatibility or locking mechanisms.
- Final validation: focused Toolkit service/repository/API OAuth tests; full
  affected Pytest suites; `uv run ruff check --fix` and `uv run ruff format` on
  affected Python paths; full `uv run ty check --error-on-warning`; staged
  pre-commit without bypass; explicit residual transaction/import/caller search.
- Scope-drift check: every one of the 25 audit-listed Toolkit contexts is removed
  or mapped to one typed completed repository operation; no unrelated model,
  integration, file, Runtime, schema, generated API, or Engine behavior is added.
- Context checkpoint: baseline service has 25 Toolkit contexts, including create
  nested OAuth/settings work and conditional GitHub validation contexts. The
  intended interface change is internal DI only. Risks are stale Platform App or
  user-installation authority between validation and mutation, Toolkit deletion or
  type/workspace drift, partial Toolkit/scope creation, and OAuth projection
  failure occurring before a write transaction completes. No cross-I/O lock is
  planned or currently justified.
