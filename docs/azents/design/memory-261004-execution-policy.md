---
title: "Historical Memory Execution Policy Design"
created: 2026-10-04
implemented: 2026-10-04
tags: [memory, backend, observability, system-settings]
document_role: primary
document_type: design
snapshot_id: memory-261004
---

# Historical Memory Execution Policy Design

- Requirements: [memory-261004/REQ](../requirements/memory-261004-execution-policy.md)
- Decisions: [memory-261004/ADR](../adr/memory-261004-execution-policy.md)

## Current behavior and gap

The shared Agent iteration core is already reused, but the consolidation host/repository add fixed token, request/tool, input percentage and working-file limits. A ten-minute deadline exists independently in discovery and ownership. The job runtime returns failed outcomes without ordinary terminal traceback logging. Consolidation saves a broad failure taxonomy in its attempt row. These contradict the requester's corrected execution/error contract.

## Mechanisms

- M1: A direct `historical_memory_execution` System Settings section contains nullable positive `max_turns` (main default: absent) and positive `timeout_seconds` (initial default: 600). Existing admin authorization, optimistic versions, auditing, API projection and Admin UI own mutation. No environment overlay or per-Agent field.
- M2: Resolve the section at dispatch and carry the immutable policy in the internal job payload. Claim and supervisor use the exact submitted deadline; host passes the remaining claim-scoped maximum turns to the existing core. Candidate handoff retains logical turns consumed by previous hosts; physical transport retries do not consume extra turns. Heartbeat and stale-owner fences remain; time limits use the admitted attempt deadline instead of a separate fixed transaction cutoff.
- M3: Replace budget admission with a fenced observational execution ledger. Physical dispatches and tools retain identity/count/usage journals, including nullable requested output, but no cumulative threshold or ratio cuts admission. Lowerers get the same optional requested output setting as main. Remove private working-file count/byte caps and memory-only result bounds in favor of shared generic tool contracts. Inventory pages remain batching, not attempt cutoffs. Published document validation stays 10k.
- M4: Persist only safe actionable provider failure categories. Internal faults, cutoffs and cancellation settle failed/cancelled state and retry metadata with null `failure_code`. The Job Runtime terminal catch and elapsed cutoff boundary emit one sanitized ERROR traceback, concrete exception kind and handler/execution identity, including when the outer Runtime deadline wins the supervisor race. Existing independent tool-error logs remain ordinary tool feedback.

## Ownership, data and migration

Repositories retain transaction lifetime and current explicit WriteSession capabilities. The ledger checks exact source/draft influence before dispatch. No model or tool I/O occurs inside DB transactions. PostgreSQL remains the System Settings and execution-history authority. Generate a linear Alembic revision for the section enum, optional output-request column, and removal of draft-capacity constraints. Do not rewrite older migrations or deployed feature snapshots. No production operation is part of this delivery.

Terminal failure settlement is metadata-only: it locks and compares the exact
active attempt, unit, generation and token, then settles failed state and retry
progress even after its elapsed cutoff. It does not restore expired model, tool,
source, draft or publication authority. A completed attempt or replacement owner
remains untouched. Runtime-first deadline cancellation quiesces execution before
settlement; external shutdown before the deadline retains recovery ownership.

## Removal and Replacement

| Removed behavior | Authority | Replacement | Absence evidence |
| --- | --- | --- | --- |
| Fixed cumulative 250k/16k and request/tool budgets | REQ-1 | Main model settings; telemetry-only ledger | Constants and cutoff checks absent |
| Fixed per-call 4k and separate 70% checkpoint | REQ-1 | Resolved main-equivalent settings | Request/host regression tests |
| Independent fixed ten-minute claim/job deadlines | REQ-2 | Admitted System Settings duration | Different-duration tests |
| Working draft 16-file/256KiB and memory-only result caps | REQ-1 | Shared generic tool contracts | Large/multi-file regression tests |
| Broad persisted internal fault/cancellation codes | REQ-3 | Null internal code plus terminal ERROR traceback | DB/log tests |
| Silent registered-handler outcome conversion | REQ-3 | Job Runtime terminal logging | caplog traceback test |

## Design Authority

- Design revision: `1`

| ID | Authority | Classification |
| --- | --- | --- |
| M1 | REQ-2; existing System Settings Spec | required |
| M2 | REQ-1/2; existing shared Agent core and durable fences | derived |
| M3 | REQ-1; ADR-D1/D3 | required |
| M4 | REQ-3; logger/Sentry and log-once conventions | required |

## Test Strategy

Primary assembled-product coverage exercises the existing Historical Memory E2E with the new effective policy and typed system-setting path. Narrow tests cover model settings above old budgets, retries/accounting, nullable output, large drafts, configurable max turns/time, authority takeover, and ERROR traceback plus null persisted internal failure. Admin API/component tests cover both controls, version conflicts, unauthorized writes and saved/default projection. Use synthetic data/disposable containers; no production DB writes or paid providers. Run affected Ruff/type/tests, generated-client consistency, migration tests, focused E2E, independent targeted review and final-SHA CI. Do not repeat a full matrix solely for mechanical ancestry changes.

## Risks and feasibility

Large working drafts/model transcripts can use more resources, as requested; configured turns/time and existing main-model windows remain the execution bounds. Retain source authorization and product publication framing. The generated migration clears historical nonactionable attempt codes when applied; this delivery does not apply it to live data. Current core, settings registry/API/UI and explicit session capabilities provide the necessary boundaries. Implementation discovery may refine local file/helper choices but must not add another cutoff, authority, fallback or live operation.

## Design Approval

- Mode: Collaborative, direct implementation instruction.
- Decision owner: requester.
- Approved scope on 2026-10-04: remove main-Agent-absent restrictions; keep only system-configurable maximum turns/time; fix internal-fault logging/persistence.
- Design revision: 1; authority IDs: M1, M2, M3, M4, derived within that explicit scope and unchanged platform contracts.
- No unresolved material mechanism or product expansion is introduced.
