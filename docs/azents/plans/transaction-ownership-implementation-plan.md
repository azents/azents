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
