---
title: "Scheduled Task Quiet Completion Design"
created: 2026-11-10
implemented: 2026-11-10
tags: [scheduled-task, backend, frontend]
document_role: primary
document_type: design
snapshot_id: quiet-261110
---

# Scheduled Task Quiet Completion Design

[Requirements](../requirements/quiet-261110-scheduled-completion.md) ·
[Decisions](../adr/quiet-261110-scheduled-completion.md)

## Current System and Scope

Task definitions already flow through root tools, management API and signed
provider controls into `scheduled_tasks`; dispatch captures immutable Toolkit
State. Completion writes one typed terminal Event before provider effects. Extend
these owners rather than introduce a second scheduler or terminal history owner.
Ship one focused PR including tests, generated surfaces and Spec ingest.

## Design Authority

Design revision: `1`.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Task permission propagated through management and immutable cycle | REQ-1, REQ-5; ADR-D1 | required |
| M2 | Explicit notification choice and reason, fenced successful-only completion | REQ-2, REQ-5; ADR-D1, D2 | derived |
| M3 | No initial Tracker; explicit progress precludes quiet completion | REQ-3; ADR-D3 | required |
| M4 | Non-notifying inspectable typed Session result and existing UI | REQ-4, REQ-6; ADR-D4 | required |
| M5 | Existing authority, transaction, lifecycle and no-replay boundaries | REQ-5; Scheduled Task Spec | existing |
| M6 | Public client generation and consistent skills/provider controls | REQ-1, REQ-6; ADR-D1, D4 | derived |

## Data, Interfaces and Lifecycle

Add `allow_silent` to the durable definition, create/replace projections, tool
schema and provider editor. Database migration sets existing definitions and
persisted cycle snapshots to false. Historical result Events gain notification
true and no suppression reason; new constructors pass values explicitly. Do not
introduce versioning or a retained compatibility parser for these shapes.

Copy permission into each admitted cycle. A started cycle never consults a later
Task definition for permission. Existing pre-start replacement removes the old
admission. Existing cancellation, archive and owner fences remain intact.

Completion takes `status`, nonblank `result`, `notify`, nullable
`suppression_reason` and `files`. Notify requires no suppression reason; silent
requires finished status, nonblank reason, no files, captured permission and no
explicit user-facing progress. Validate before external file preparation where
possible, and repeat authoritative permission/progress checks in the terminal
transaction. Canonical Event stores choice/reason. Duplicate recovery uses the
saved payload and never revalidates/replays original external effects.

The canonical commit still releases the cycle/Task and supplies terminal Run
identity. Channel effect snapshot carries the saved choice. Silence bypasses reply
plans (including parent forwarding/broadcast), not canonical completion. Tracker
cleanup remains separate. No-send must not be reported as failed delivery.

Skip initial Tracker claims for permitted cycles at their existing repository
boundary. Explicit progress records that the occurrence has begun communication;
silent completion is then structurally rejected. Model guidance avoids routine
progress, reports findings/meaningful external changes and fails transparently.
Uncertain tool calls are not silently retried.

## Presentation and Notifications

Add an accessible unchecked-by-default checkbox to existing create/edit surfaces,
a policy summary to list/detail and registration, and the running-occurrence
policy-change note. Preserve draft state/error behavior. Translate all supported
locales naturally. Keep the omission condition in the existing objective.

Extend the existing public chat projection and web/iOS conversation renderers as
needed so a quiet result exposes a collapsed completion summary, reason and time.
No ordinary empty assistant message or completion push. Keep execution result and
actual delivery outcome distinct; do not claim sent merely because notify=true.
Inspect terminal notification paths, not only channel result publication.

Update Scheduled Task and Routine skills together: notification is independent of
scheduled mandatory execution versus usefulness judgment. Keep destinations opaque
and exact and do not add unsupported Task management operations.

## Security, Rollout and Operations

Permission never authorizes external changes. All existing authorization and owner
checks remain. Apply the schema/data migration with the release's existing
migration mechanism; no live migration or deployment is part of this work. A
rollback must not reinterpret silent results as reports or automatically replay
them. Meaningful-report judgment remains a model-guidance limitation, explicitly
covered by conservative examples. Preserve ordinary logging integration.

## Removal and Replacement

| Old behavior/surface | Authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Unconditional initial Tracker | REQ-3 | Permission-aware claim | Repository claim | focused claim tests |
| Unconditional terminal reply | REQ-2, REQ-4 | Saved notification choice | canonical commit/effect preparation | silent and report tests |
| Output-obligation-only Skill routing | REQ-6 | Execution obligation routing | both release skills | package tests and text review |
| Generated contracts without policy | REQ-1, REQ-6 | source-generated clients | API schema generation | generated diff/typecheck |
| Terminal UI without quiet state | REQ-4 | collapsed detail | existing conversation projection | UI/unit/story coverage |

No scheduler, history table, retry/fallback mode or existing definition is removed.

## Test Strategy

Use existing Scheduled Task minimal E2E management flow for opt-in persistence and
edit/list visibility; do not expand E2E into a combinatorial matrix. Deterministic
repository/service/tool tests own failed/unauthorized/files/progress rejection,
immutable policy across replacement, silent terminalization, duplicate recovery,
Tracker suppression and channel no-send. Public route/schema tests and generated
client checks own the wire shape. Existing web pure-state stories/unit checks own
default/edit/error/quiet history rendering, with iOS checks if its projection changes.

Use existing local database fixture configuration and CI test prerequisites; no
production credentials, DB writes, live provider messages or new fixture service.
Capture command/environment/results in the PR. Run focused tests, backend lint and
typecheck, web formatting/lint/typecheck, schema generation, docs validation, and
exact-head required CI. Live provider tests are excluded without explicit setup;
report local prerequisite failures rather than treating skips as proof.

## Feasibility and Approval Scope

Existing immutable snapshots, typed Events and post-commit provider effects offer
credible insertion points for M1–M6. Final evidence must verify notification and
conversation consumers, persisted snapshot migration and generated interfaces.
No product delta is authorized by feasibility findings.

Local implementation verification: backend Ruff/ty, 149 focused repository,
service and tool tests, PostgreSQL migration preservation through
downgrade/re-upgrade, 854 web unit tests, web typecheck/lint, four Chromium
Storybook cases, and eleven E2E support tests passed. Public clients were
source-generated. Independent review's rollback data-loss finding was corrected
and targeted re-review passed. Assembled E2E and exact-head CI evidence are
recorded on the implementation PR; local verification does not claim deployment.

## Design Approval

Approved revision: `1`. Exact authority IDs: `M1, M2, M3, M4, M5, M6`.

Mode: Collaborative. Decision owner: requester. On 2026-11-10 the requester
approved the presented registration/reporting/lifecycle behavior and asked to
implement it. Revision 1 mechanisms M1–M6 are a direct decomposition of that scope
and retained system boundaries, not additional product or technical modes. New
material choices outside this scope require separate confirmation. Merge and
deployment remain excluded.
