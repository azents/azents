---
title: "Repository Transaction Ownership Implementation Plan"
created: 2026-09-08
tags: [backend, architecture, database]
---

# Repository Transaction Ownership Implementation Plan

- Requirements: [transaction-260908/REQ](../requirements/transaction-260908-repository-ownership.md)
- Decisions: [transaction-260908/ADR](../adr/transaction-260908-repository-ownership.md)
- Design: [transaction-260908/DESIGN](../design/transaction-260908-repository-ownership.md), revision 1
- Execution authority: direct requester implementation instruction for M1–M5.
- Design delta: None.
- Independent reviewer: `/root/tx-review` (read-only).
- Integration owner: `/root`.

## Resumed Stack — 2026-10-01

The requester authorized continuous stacked-PR delivery until #1718 is complete.
The remaining current inventory is delivered in this branch chain before CI:

1. Runtime Control read ownership.
2. Engine read ownership.
3. Agent service repository operations.
4. Chat Workspace, Discord settings, idle continuation, and any evidence-backed
   residual application entrypoints.
5. Final inventory, validation, Spec promotion, implementation marking, and plan
   cleanup.

Each PR uses the previous phase branch as its base. Design delta remains `None`;
M1–M5 and REQ-1 through REQ-5 remain the complete authority.

## Stack Extension — 2026-10-01

The post-Phase-15 lexical checkpoint found 598 remaining session contexts across
122 non-repository application files. This is discovery evidence, not 598 confirmed
violations, and it invalidates the earlier assumption that one residual PR plus one
validation PR would complete the issue. Keep the existing PR numbering as historical
stack labels, but continue sequential stacked delivery by bounded domain batches until
every context has a call-path-backed corrected or excluded disposition. Phase 16 owns
the already assigned Chat Workspace, Discord lifecycle/settings, and idle-continuation
slice. Later branches must cover Engine execution/tools, Chat and mailbox, Runtime and
lifecycle workers, account/workspace/configuration services, API/CLI entrypoints, and
other residual groups before final validation and plan cleanup.

Phase 17 starts the Engine execution/tools group with Tool Search working-set,
AGENTS.md and Claude Rules appendix-dedupe, and Todo Toolkit State. It moves the
assigned persisted payloads to pure core models and their completed transaction
lifetimes to repository operations while preserving compaction's existing atomic
working-set reset. Later Engine phases retain model execution, provider output,
MCP/cloud snapshots, and residual event-compaction ownership.

Phase 18 continues that group with Raw MCP, AWS, GCP, and GitHub MCP tool
snapshots plus GitHub selected-installation state. Provider discovery and token
exchange remain outside completed repository operations; MCP OAuth/configuration,
model execution, provider output, and compactor ownership remain later phases.

Phase 19 moves model-visible Memory CRUD/search, Memory prompt scope and summary
reads, and Session History authority/read compositions into completed repository
operations. Runtime behavior/project reads, Scheduled/Subagent tools, MCP OAuth,
model execution, provider output, and compactor ownership remain later phases.

Phase 20 moves Runtime Toolkit behavior/configuration and Session Project reads,
plus MCP OAuth connection load and refresh success/failure finalization, into
completed repository operations. OAuth provider HTTP refresh remains outside
database transactions, and stale credential snapshots still yield to concurrent
refresh. Scheduled/Subagent tools, model execution, provider output, and
compactor ownership remain later phases.

Phase 21 moves the five Scheduled Toolkit and eight Subagent Toolkit direct
session contexts behind completed repository operations. Scheduled channel
registration/deletion and Subagent broker wake/stop plus tree invalidation remain
post-commit effects. Spawn retains one final atomic child-creation transaction
that revalidates the invoking Run and root-tree capacity after detached pure
inference/fork preparation. Model execution, provider output, and compactor
ownership remain later phases.

Phase 22 moves Provider Output scope, retry-preflight, and cleanup-protection
reads into completed repository operations while retaining the existing
database-only metadata admission inside the same transaction as model/tool Event
commit. Object upload and compensation delete remain outside database
transactions. Engine execution and compactor/filter ownership remain later
phases.

## Delivery Boundaries

1. Correct the title-generation and ChatGPT OAuth persistence boundary as one
   independent implementation PR. Provider refresh and model/title projection
   execute after completed repository operations.
2. Correct the confirmed Project and Mailbox external-I/O overlaps and extract
   their bounded database-only repository operations. Their shared Toolkit State
   dependency follows in a dependent implementation PR.
3. Complete remaining transaction ownership and confirmed external-I/O violations
   by domain, using the exhaustive inventory to determine bounded PR interfaces.
   Open each delivery PR before monitoring CI or starting a dependent phase.
   Do not close the overall issue while any confirmed violation or coverage gap
   remains.
4. Re-run entrypoint and indirect-call inventory, report unavoidable locking
   exceptions, verify affected E2E/required CI, promote current Specs, and remove
   this effort's temporary plans after verified completion.

Later phases' exact file partition remains an execution decomposition, not authority
to change behavior. Record it before those edits. The six research areas are
External Channel; Runtime/Projects; Session/Agent lifecycle; models/integrations/
files; account/workspace/configuration; and non-service entrypoints.

## Shared Contracts and Constraints

M1–M3 require complete typed repository calls, external work outside transactions,
and preservation of existing atomicity/authority. M4 owns inventory, evidence,
tests, and delivery. M5 owns lock avoidance and the exception ledger.

Repository code never calls service orchestration or arbitrary external
callbacks. Shared DTO/helper relocation requires caller inventory and explicit
ownership assignment. No generated API, schema, dependency, migration, provider,
retry, or configuration changes are planned.

Read-only research can overlap implementation; reports identify the baseline SHA
and distinguish changed-line evidence from baseline findings. Implementation
owners do not edit one another's source files or shared documents.

## Verification and Cleanup

Each phase includes scoped tests, Ruff/format, configured type checks,
pre-commit, one independent review, and required CI. Existing E2E flows remain
product-contract evidence. Testenv prerequisites are used only where needed;
secrets are never recorded. Record exact missing prerequisites rather than
claiming skipped tests pass.

At completion, report residual entrypoints, exclusions, stale-authority/rollback
evidence, and each unavoidable cross-I/O lock (or a verified none). Standalone
memory coordination and distributed Redis-loss safety are distinct checks.
Do not merge PRs or modify live infrastructure. Remove completed clean managed
worktrees and their Project registrations when no further edits are needed.
