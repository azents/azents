---
title: "Design approval scope mapping audit — 2026-10-26"
created: 2026-10-26
tags: [documentation, process, audit]
document_role: supporting
document_type: supporting-audit-report
---

# Design Approval Scope Mapping Audit

This supporting record supplies explicit revision and mechanism-set mappings for
two existing requester-approved implementation scopes. It preserves the original
design records and their approval provenance. It is not a new Design approval,
implementation-status update, or source of authority for additional mechanisms.

## Shell Waiting

- Design: [shell-261022/DESIGN](shell-261022-interruptible-wait.md).
- Mode: collaborative, direct implementation request.
- Decision owner: requester.
- Approval date: 2026-10-22.
- Recorded design revision: `1`.
- Exact mapped authority-ID set: `M1`, `M2`, `M3`, `M4`, `M5`.
- Material scope: cancellable owner-scoped Runner long-poll; ordinary-command
  participation with explicit fire-and-forget exclusion; ten-second shell-result
  yields with independent output collection; non-consuming lifecycle observations
  and the existing committed-result observation position; preservation of process,
  stop, generation, and retention ownership.
- Provenance: the requester asked to implement the presented non-consuming
  long-poll proposal on October 22. The proposal included time-only wait, explicit
  observation cancellation without process termination, output separation, and
  completion-before-registration and repeated-observation safeguards. The existing
  Requirements confirmation, ADR, and Design approval record describe that scope.
- Mapping boundary: M1-M3 identify the approved proposal and M4-M5 identify its
  documented derived/existing consistency boundaries. This mapping does not claim
  that the requester separately approved a written revision-ID list or enlarge
  the approved product scope.

## Repository Transaction Ownership

- Design: [transaction-260908/DESIGN](transaction-260908-repository-ownership.md).
- Mode: collaborative, direct implementation request.
- Decision owner: requester.
- Approval date: 2026-09-08 (KST).
- Recorded design revision: `1`.
- Exact mapped authority-ID set: `M1`, `M2`, `M3`, `M4`, `M5`.
- Material scope: database-only repository-owned transactions, repository
  composition for atomic work, external I/O between completed operations,
  preservation and revalidation of existing atomicity/authorization, complete
  boundary inventory with bounded verification, and explicit reporting of any
  unavoidable cross-I/O serialization exception.
- Provenance: the September 8 requester direction states that open transactions
  perform only database work, repositories may compose narrower repositories,
  and API/Redis work inside a transaction is a more serious violation. The
  existing Design approval already explicitly enumerates M1-M5 as consequences
  of that direction, the implementation request, and the exception-reporting rule.
- Mapping boundary: revision `1` is the revision whose unchanged M1-M5 table is
  enumerated by that approval record. No separate revision-bound written approval
  is claimed. New mechanisms and locking exceptions remain outside that record's
  authorization and require their existing decision/reporting process.

## Verification and Limits

- Compared the current mechanism tables, Requirements/ADR references, existing
  approval statements, and available requester conversation evidence.
- Original design content and material-mechanism IDs are unchanged. Neither
  snapshot is rewritten as a current implementation specification.
- This report fixes approval traceability, not a claim that all historical designs
  meet newer authoring templates or that the implementation was revalidated here.
- Product behavior, public interfaces, approval scope, and implementation status
  are unchanged; no product E2E change is warranted for this documentation-only
  record. Validate documentation frontmatter/catalog and normal documentation CI.
