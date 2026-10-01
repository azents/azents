---
title: "Transaction Ownership Phase 20: Engine Runtime Reads and MCP OAuth"
created: 2026-10-01
tags: [backend, engine, runtime, mcp, oauth, architecture, database]
---

# Phase Execution Plan

- Phase: `20, Engine Runtime reads and MCP OAuth persistence`
- Branch/base: `refactor/transaction-ownership-261001-8-engine-runtime-reads` → `main` at `a498ba899` after PR #2013 merged
- PR boundary: replace transaction ownership for Builtin Runtime behavior/Project reads and MCP OAuth connection load, refresh finalization, and failure finalization with typed completed repository operations.
- Inputs: Phase 19 merged Memory/Session History operations, PR #2013, and the bounded 57-context/11-file Engine lexical checkpoint.
- Deliverables: completed Runtime behavior and Session Project reads, completed MCP OAuth preflight/finalize operations, unchanged refresh/concurrency behavior, and a corrected Engine configuration checkpoint.
- Non-goals: Runtime provider calls, MCP discovery/tool execution, Scheduled/Subagent tools, model execution, provider output, compactor ownership, public schemas, persistence schema, retry/fallback behavior, or new locks.
- Interfaces: Runtime desired/applied selection and authority projection, unavailable prompt behavior, Project ordering, MCP connection status/token freshness, external refresh timing, stale-snapshot detection, reconnect-required policy, errors/logging, and cancellation remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session contexts from the assigned Builtin and MCP paths; repository code receives no services, Runtime/provider clients, HTTP work, or application callbacks.
- Absence verification: assigned direct-session search, repository-to-service import search, caller inventory, runtime authority/project tests, OAuth fresh/refresh/failure/concurrency tests, and transaction-closure tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Builtin Runtime reads | `/root` | Runtime behavior/Project paths in `engine/tools/builtin.py`, repository/tests | Agent Runtime, Runtime Profile, Session Project repositories | Completed detached reads preserving prompt and authority | Builtin Runtime prompt/project tests and boundary tests |
| MCP OAuth operations | `/root` | `engine/tools/mcp.py`, repository/tests | MCP OAuth connection repository | Completed load, refresh-finalize, and failure-finalize operations around external OAuth HTTP | MCP OAuth focused tests, concurrency/stale snapshot tests |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | Assigned workstreams | Corrected configuration contexts and remaining classification | lexical/call-path search; no completeness claim beyond assigned paths |

- Integration order: extract Runtime read results, migrate Builtin callers, extract MCP OAuth preflight/finalize contracts, keep HTTP refresh outside transactions, migrate callers, add repository tests, update Specs, then run the residual checkpoint.
- Independent review: `/root/issue-hardening-review` performs one read-only review after the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, focused Builtin/MCP pytest, pre-commit, direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve authority, ordering, refresh timing, stale-write prevention, errors, logging, and cancellation; add no lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism.
- Context checkpoint: latest `main` includes PR #2013. This phase owns the six assigned Runtime/MCP contexts; Scheduled/Subagent and Engine execution/provider/compaction remain later batches.

## Implementation Checkpoint

- `EngineRuntimeToolReadRepository` owns completed Runtime behavior/configuration
  and Session Project reads; existing unavailable projection, desired/applied
  authority, and Engine path sorting are unchanged.
- `MCPOAuthRuntimeOperationRepository` owns completed connection loads and
  row-locked refresh success/failure finalization. OAuth provider HTTP remains
  outside database transactions, and stale snapshots yield to concurrent
  credential changes.
- Fresh tokens skip refresh, missing refresh authority and current
  `invalid_grant` evidence retain reconnect-required behavior, and transient
  failures preserve the connected row and existing logging.
- Assigned `builtin.py` and `mcp.py` direct session contexts are zero; the new
  repositories import no service, Engine, Runtime/provider client, HTTP, or
  callback surface.
- Focused Runtime/MCP/Builtin/repository validation: 80 tests passed. Full
  backend validation after a frozen environment sync: 6,821 tests passed and 3
  skipped. Backend `ty --error-on-warning` and repository-wide pre-commit passed.
- Independent reviewer `/root/issue-hardening-review` reported zero findings and
  required no targeted re-review.
- A bounded post-change lexical scan finds 51 remaining session-manager context
  entries across 9 Engine files. Scheduled/Subagent, execution, provider-output,
  and compaction ownership remain later batches.
- Design delta: `None`.
