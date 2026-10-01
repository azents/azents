---
title: "Transaction Ownership Phase 17: Engine Tool State"
created: 2026-10-01
tags: [backend, engine, toolkit, architecture, database]
---

# Phase Execution Plan

- Phase: `17, Engine tool-state completed operations`
- Branch/base: `refactor/transaction-ownership-261001-5-engine-execution` → `refactor/transaction-ownership-261001-4-residual-services`
- PR boundary: replace Engine tool-state transaction ownership for deferred Tool Search working sets, builtin-agent and Claude-rules appendix dedupe, and Todo state with typed completed repository operations; classify directly dependent Engine tool contexts for follow-up batches.
- Inputs: Phase 16 completed service/Worker operations and the extended transaction-ownership inventory.
- Deliverables: repository-owned completed state reads/mutations for the assigned Engine tool stores, unchanged tool discovery/prompt behavior, and a bounded Engine residual checkpoint.
- Non-goals: model execution loop restructuring, provider lowering, tool schema or prompt changes, public tool behavior, persistence schema, retry/fallback behavior, or new locks.
- Interfaces: existing per-Agent/per-Session state keys, owner-generation/session authority where present, dedupe hashes, Tool Search recency order, Todo validation/error behavior, and cancellation semantics remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session-manager contexts from the assigned Engine tool-state modules and replace them with completed repository calls.
- Absence verification: direct-session search in assigned paths, repository-to-service import search, caller inventory, and unchanged state-key/hash/order tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deferred Tool Search state | `/root` | `engine/tooling/tool_search.py`, completed repository/tests | Toolkit state persistence | Completed load/activate/clear operations preserving recency order | Tool Search focused tests and transaction-closure tests |
| Appendix dedupe state | `/root` | `engine/tools/builtin_agents.py`, `engine/tools/claude_rules.py`, completed repository/tests | Toolkit state persistence | Completed load/update operations preserving content hashes | Builtin Agents and Claude Rules tests |
| Todo state | `/root` | `engine/tools/todo.py`, completed repository/tests | Toolkit state persistence | Completed Todo load/update operations | Todo focused tests and error-contract checks |
| Engine residual checkpoint | `/root` | phase plan and bounded inventory evidence | Assigned workstreams | Corrected and remaining Engine context classification | lexical/call-path search; no completeness claim beyond assigned paths |

- Integration order: extract completed Toolkit-state operations, migrate each store without changing public interfaces, add transaction-boundary tests, update related Spec paths, then run the Engine residual checkpoint.
- Independent review: `/root/issue-hardening-review` performs one read-only review after all implementation workstreams are complete and the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, focused Engine tool pytest, pre-commit, direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve state identities, atomicity, errors, prompt/tool behavior, and ordering; add no lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism.
- Context checkpoint: PR #2008 is the current stack base. The 598-context checkpoint remains discovery evidence; this phase handles only the assigned Engine tool-state subset before later Engine execution and provider-output batches.

## Implementation Checkpoint

- Persisted Tool Search, AGENTS.md appendix, Claude Rules appendix, and Todo
  payloads now use pure `core/engine_tool_state.py` models.
- `repos/toolkit_state/engine.py` owns completed state reads and mutations,
  owner-generation fencing, existing Toolkit State identities, and optimistic
  conflict retry.
- Successful compaction retains its existing atomic group by using the
  repository's database-only composed working-set clear in the summary/head
  transaction; the repository also exposes a completed independent clear.
- The four assigned Engine modules contain no SQLAlchemy, `AsyncSession`,
  `SessionManager`, or session context entry. The new repository imports no
  service module.
- Focused repository and assigned Engine validation: 193 tests passed after the
  explicit typed-operation boundary and repository transaction tests were added.
- Independent reviewer `/root/issue-hardening-review` reported zero findings and
  required no targeted re-review.
- A bounded post-change lexical scan finds 77 remaining session-manager context
  entries across 17 Engine files. They belong to later execution, provider,
  MCP/cloud snapshot, and event-compaction ownership batches; this checkpoint
  makes no call-path completeness claim for those paths.
- Design delta: `None`.
