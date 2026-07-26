---
title: "Unified Agent Input Mailbox Phase 7: Spec Promotion"
created: 2026-07-26
updated: 2026-07-26
tags: [agent, mailbox, spec, documentation, plan]
---

# Mailbox Phase 7: Spec Promotion

## Phase Execution Plan

- Phase: `7 — Spec promotion and snapshot implementation`
- Branch/base: `feature/mailbox-260726-spec` → `feature/mailbox-260726-validation`
- PR boundary: Apply the single Phase 6 `/spec-review` result to current living specs, then mark the completed Requirements and Design snapshot implemented. Do not change runtime behavior, validation fixtures, or accepted ADR decisions.
- Inputs: Phase 6 validation report [`mailbox-260726-validation-report-2026-07-26.md`](../design/mailbox-260726-validation-report-2026-07-26.md), the completed [Phase 6 plan](mailbox-260726-phase-6-e2e-validation.md), and `mailbox-260726` Requirements/ADR/Design.
- Deliverables:
  - Update `chat-session-resync`, `conversation`, and `goal` specs for canonical mailbox terminology, typed pending REST/WS contract, native Web lifecycle, correlation, and relevant Goal continuation behavior.
  - Refresh each changed spec's `code_paths`, `last_verified_at`, and `spec_version` according to its actual current behavior.
  - Add `implemented: 2026-07-26` to the Requirements and Design documents only after the validation report and implementation stack evidence are complete.
- Non-goals:
  - No source, API, generated client, test, migration, Requirements content, or ADR edits.
  - Do not rerun `/spec-review`; Phase 6 recorded the one required result.
  - Do not modify the accepted ADR.
- Interfaces:
  - Specs describe current behavior only; Requirements/Design remain historical snapshots after implementation date is added.
  - External Channel and other matched-no-update specs retain their Phase 6 rationale; they are not edited without a recorded impact.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Spec promotion and snapshot finalization | `/root/mailbox-implementer` | `docs/azents/spec/{flow/chat-session-resync.md,domain/conversation.md,domain/goal.md}`; Requirements/Design snapshot documents; Phase 7 plan | Phase 6 report/spec-review | Current specs and immutable implemented snapshot markers | Docs index, spec/snapshot validation, diff scope, representative checks |
| Independent review | `/root/mailbox-reviewer` | Read-only docs diff and Phase 6 report | Implementer validation | Grounded findings and recheck verdict | Accurate current behavior, correct spec impact scope, snapshot/ADR immutability |

- Integration order:
  1. Read the Phase 6 report's recorded spec-review impact and implementation evidence.
  2. Update only the three impacted living specs from that record.
  3. Add same-date implementation markers to Requirements and Design; leave ADR untouched.
  4. Validate documentation indexes, snapshot lifecycle, and scope drift.
  5. Request independent review; apply findings and recheck.
- Final validation: docs index check, snapshot/spec validation, `git diff --check`, representative source-path review, and reviewer `CLEAN`.
- Scope-drift check: the diff must contain only this plan, the three impacted specs, and Requirements/Design implementation markers.
