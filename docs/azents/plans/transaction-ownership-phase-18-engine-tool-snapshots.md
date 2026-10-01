---
title: "Transaction Ownership Phase 18: Engine Tool Snapshots"
created: 2026-10-01
tags: [backend, engine, toolkit, mcp, architecture, database]
---

# Phase Execution Plan

- Phase: `18, Engine MCP and GitHub Toolkit State snapshots`
- Branch/base: `refactor/transaction-ownership-261001-6-engine-snapshots` → `refactor/transaction-ownership-261001-5-engine-execution`
- PR boundary: replace transaction ownership for Raw MCP, AWS, GCP, and GitHub MCP tool snapshots plus GitHub selected-installation state with typed completed repository operations.
- Inputs: Phase 17 completed Engine tool-state operations, PR #2010, and the bounded 77-context/17-file Engine lexical checkpoint.
- Deliverables: pure persisted snapshot/selection models, repository-owned completed load/replace operations, unchanged snapshot identities/hashes/filtering, and a corrected Engine snapshot checkpoint.
- Non-goals: MCP OAuth or Toolkit configuration reads in `mcp.py`, provider discovery/token exchange, model execution, provider output, compactor ownership, tool schemas, public behavior, persistence schema, retry/fallback behavior, or new locks.
- Interfaces: existing per-Agent/per-Session namespace and state-name identities, owner-generation/session authority, snapshot schema v1, server URL validation, deterministic tool hashes and order, selected-installation sentinel behavior, and background stale-owner handling remain unchanged.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`.
- Authority references: `transaction-260908/REQ-1` through `REQ-5`, `transaction-260908/ADR-D1` through `ADR-D3`, and `transaction-260908/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations: remove direct session contexts and typed Toolkit State handles from the assigned Engine snapshot/selection paths; repository code receives no services, provider clients, Runtime I/O, or application callbacks.
- Absence verification: direct-session/ToolkitStateStore search in assigned paths, repository-to-service import search, caller inventory, exact identity/payload tests, and unchanged hash/order/filter tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared MCP snapshot persistence | `/root` | `core` snapshot models, `repos/toolkit_state`, `engine/tools/mcp_base.py` | Toolkit State persistence | Completed load/replace operations for typed MCP snapshots | MCP base focused tests and transaction-closure tests |
| AWS/GCP snapshot callers | `/root` | `engine/tools/aws.py`, `engine/tools/gcp.py`, tests | Shared snapshot repository | Existing endpoint/project validation and deterministic reconstruction through completed operations | AWS/GCP focused tests |
| GitHub selection and snapshots | `/root` | `engine/tools/github.py`, related tests | Shared snapshot repository | Completed selected-installation and lazy installation snapshot reads | GitHub selection/snapshot tests and owner-fence tests |
| Engine residual checkpoint | `/root` | phase/master plans and bounded inventory evidence | Assigned workstreams | Corrected snapshot contexts and remaining Engine classification | lexical/call-path search; no completeness claim beyond assigned paths |

- Integration order: move pure snapshot/selection payload contracts, add explicit repository operations, migrate Raw MCP then AWS/GCP and GitHub callers, add boundary/identity tests, update related Specs, then run the residual checkpoint.
- Independent review: `/root/issue-hardening-review` performs one read-only review after the integrated diff is stable.
- Final validation: root runs changed-path Ruff and format, full backend `ty`, focused MCP/AWS/GCP/GitHub pytest, pre-commit, direct-session/import searches, and creates the next stacked PR.
- Scope-drift check: preserve state identities, hashes, order, endpoint filtering, stale-owner handling, errors, and external-I/O order; add no lock, queue, retry, fallback, API, schema, protocol, or configuration mechanism.
- Context checkpoint: PR #2010 is the current stack base. This phase owns only the assigned Toolkit snapshot/selection subset; `mcp.py` OAuth/configuration reads and the remaining Engine execution/provider/compaction contexts stay in later batches.

## Implementation Checkpoint

- MCP tool snapshot items/state and GitHub selected-installation state now use
  pure `core/engine_tool_state.py` models.
- `McpToolSnapshotStore` and `GitHubSelectedInstallationStore` own completed
  load/replace operations, existing optimistic retry, and owner-generation fencing.
- Raw MCP, AWS, GCP, and GitHub snapshot/selection paths contain no direct session
  context or typed Toolkit State handle.
- External MCP discovery, token issuance, artifact storage, and tool execution
  remain outside repository transactions.
- Focused repository and assigned Toolkit validation: 56 tests passed; full
  backend `ty --error-on-warning` passed.
- Independent reviewer `/root/issue-hardening-review` reported zero findings and
  required no targeted re-review.
- A bounded post-change lexical scan finds 68 remaining session-manager context
  entries across 13 Engine files. This phase makes no call-path completeness claim
  for those later execution, OAuth/configuration, provider-output, compaction,
  memory, scheduling, history, and subagent batches.
- Design delta: `None`.
