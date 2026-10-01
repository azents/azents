---
title: "Transaction Ownership Phase 19: Engine Memory and Session History"
created: 2026-10-01
tags: [backend, engine, memory, conversation, architecture, database]
---

# Phase Execution Plan

- Phase: `19, Engine Memory and Session History operations`
- Branch/base: `refactor/transaction-ownership-261001-7-engine-tool-services` → `refactor/transaction-ownership-261001-6-engine-snapshots`
- PR boundary: replace transaction ownership for model-visible Memory CRUD/search, Memory prompt scope/read preparation, and the three Session History tools with explicit completed repository operations.
- Inputs: Phase 18 completed Toolkit snapshot operations, PR #2011, and the bounded 68-context/13-file Engine lexical checkpoint.
- Deliverables: repository-owned completed Memory and Session History operations, unchanged scope/authority/pagination/rendering behavior, and a corrected Engine tool-service checkpoint.
- Non-goals: Runtime behavior/project reads in `builtin.py`, Scheduled/Subagent tools, MCP OAuth/configuration, model execution, provider output, compactor ownership, public schemas, persistence schema, retry/fallback behavior, or new locks.
- Interfaces: Agent/User Memory scope rules, Team Session user-scope rejection, exact-to-partial search fallback, CRUD error/result text, active-root privacy authority, history cursors/order/limits, event allowlists, tool-result pagination, and owner-generation fencing remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session contexts from assigned Memory/History tool paths and Memory-related Builtin prompt/scope paths; repository code receives no services, external I/O, or application callbacks.
- Absence verification: assigned direct-session search, repository-to-service import search, caller inventory, scope/authority/error tests, cursor/order tests, and repository transaction-closure tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Memory completed operations | `/root` | `engine/tools/memory.py`, repository/tests | Memory repository primitives | Explicit save/list/get/search/delete operations preserving scope and fallback | Memory focused tests and transaction-closure tests |
| Memory prompt and scope | `/root` | Memory-related paths in `engine/tools/builtin.py`, repository/tests | Memory operations, Session scope read | Completed associated-user resolution and prompt collection | Builtin Memory read/write/prompt tests and owner-fence tests |
| Session History operations | `/root` | `engine/tools/session_history.py`, repository/tests | Session, WorkspaceUser, history/message repositories | Completed search/read/tool-result operations preserving privacy and pagination | Session History focused tests and boundary tests |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | Assigned workstreams | Corrected Memory/History contexts and remaining classification | lexical/call-path search; no completeness claim beyond assigned paths |

- Integration order: extract detached result contracts and explicit Memory operations, migrate tool handlers and prompt reads, extract Session History authority/read compositions, migrate handlers, add repository tests, update Specs, then run the residual checkpoint.
- Independent review: `/root/issue-hardening-review` performs one read-only review after the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, focused Memory/Builtin/Session History pytest, pre-commit, direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve scope, authority, ordering, pagination, rendering, errors, and publication behavior; add no lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism.
- Context checkpoint: PR #2011 is the current stack base. This phase owns the 11 assigned Memory/History-related contexts; Runtime behavior/project reads, Scheduled/Subagent, MCP OAuth/configuration, and Engine execution/provider/compaction remain later batches.

## Implementation Checkpoint

- `MemoryOperationRepository` owns completed save/list/get/exact-to-partial
  search/delete operations, prompt summary loading, and associated User scope
  resolution.
- `SessionHistoryOperationRepository` owns active-root/privacy authority and each
  root search, within-Session search, visible history page, and selected tool
  Event read.
- Engine handlers retain model input validation, cursor decoding, rendering, and
  existing `FunctionToolError` text after repository completion.
- Assigned `memory.py` and `session_history.py` direct session contexts are zero;
  Memory-related Builtin prompt/scope contexts are removed. The two remaining
  Builtin contexts belong to the later Runtime behavior/project read phase.
- Focused repository and assigned Engine validation: 110 tests passed; full
  backend `ty --error-on-warning` passed.
- Independent reviewer `/root/issue-hardening-review` reported zero findings after
  the second main/stack rebase and required no targeted re-review.
- A bounded post-change lexical scan finds 57 remaining session-manager context
  entries across 11 Engine files. This phase makes no call-path completeness
  claim for later Runtime read, Scheduled/Subagent, MCP OAuth/configuration,
  execution, provider-output, and compaction batches.
- Design delta: `None`.
