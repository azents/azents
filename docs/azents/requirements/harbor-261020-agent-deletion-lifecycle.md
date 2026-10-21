---
title: "Testable Agent Deletion Lifecycle Requirements"
created: 2026-10-20
implemented: 2026-10-20
tags: [agent, lifecycle, backend, testing]
document_role: primary
document_type: requirements
snapshot_id: harbor-261020
---

# Testable Agent Deletion Lifecycle Requirements

- Snapshot: `harbor-261020`
- Document reference: `harbor-261020/REQ`

## Problem

Agent deletion already has durable coordination and safety gates, but cleanup ownership
and completion checks are distributed across manually maintained lists. A newly added
resource can be omitted, preventing terminal deletion without a focused regression
identifying the missing owner. Session lifecycle has stronger explicit ownership and
validation contracts that should inform the Agent boundary.

## Primary System Outcome

Agent deletion completes only after every Agent-owned cleanup responsibility is
satisfied, with independent deterministic tests proving each responsibility and the
coordination between them.

## Supporting Scenarios or Effects

- Developers can identify the responsible cleanup boundary when deletion fails.
- Historical references and shared resources do not accidentally block or disappear
  during terminal Agent deletion.
- Users can distinguish an Agent awaiting deletion from an active Agent or one whose
  deletion encountered an error, and can inspect it without making new changes.

## Goals

- Make deletion ownership, dependency constraints, and completion obligations explicit.
- Make responsible cleanup units testable independently of a full application stack.
- Detect omissions before production through unit and PostgreSQL integration coverage.

## Non-Goals

- Change public deletion permissions, retention policies, or asynchronous semantics.
- Replace Session lifecycle ownership or bypass its retention/purge behavior.
- Add deletion cancellation, forced purge, manual retry controls, configuration modes,
  or a new versioning system.
- Merge, deploy, or manually repair production data as part of design approval.

## Requirements

### REQ-1. Preserve deletion safety and observable behavior

Existing authorized asynchronous deletion and admission fencing remain unchanged.

**Acceptance criteria**

- Existing decommission jobs continue safely after deployment.
- Finite archived-session retention, Session purge ownership, current job attempt and
  lease identity, and current-generation Runtime deletion acknowledgement remain gates.
- No partially cleaned Agent is reported as deleted.

### REQ-2. Explicit and complete cleanup ownership

Every resource relevant to Agent deletion has an explicit deletion or preservation
responsibility and a verifiable completion condition.

**Acceptance criteria**

- New referencing database resources and external resources cannot silently escape
  ownership coverage.
- Invalid dependencies, duplicate ownership, and missing required cleanup obligations
  are detected before terminal root deletion.
- Installed PostgreSQL deletion constraints are checked against declared ownership.

### REQ-3. Independent deterministic testing

Each cleanup responsibility can be exercised without booting the complete product.

**Acceptance criteria**

- Tests isolate inputs, dependencies, successful cleanup, incomplete cleanup, and failure.
- Ordering, duplicate execution, retry, cancellation, and lost ownership can be tested
  without fixed sleeps or paid model calls.
- Real PostgreSQL tests verify constraint behavior and transaction rollback rather than
  relying solely on mocked SQL calls.

### REQ-4. Safe failure and continuation

Interrupted or failed cleanup does not bypass unfinished work or corrupt completion.

**Acceptance criteria**

- Failures identify the responsible cleanup boundary and preserve safe retry behavior.
- Restart or retry converges without double destructive effects or premature completion.
- Database transactions do not span external provider or object-store I/O.
- Stale workers cannot finalize another worker's current attempt.

### REQ-5. Preserve unrelated resources and retained evidence

Deleting one Agent affects only its authorized destructive scope.

**Acceptance criteria**

- Shared provider, Workspace, and other Agents' resources remain usable.
- Retained historical identity, status, and counters remain intact.
- Agent deletion continues to delegate Session destruction to the existing Session path.

### REQ-6. Layered verification and incremental delivery

Pipeline-level tests own detailed deletion correctness; E2E verifies the representative
user-facing completion path.

**Acceptance criteria**

- Permission/policy admission, Session retirement and purge wait, external cleanup,
  Runtime acknowledgement, finalization, and retry/ownership boundaries have focused tests.
- E2E waits for actual deletion rather than asserting only that DELETE was accepted.
- Emergency fix, lifecycle structure, pipeline coverage, and representative E2E changes
  remain separately reviewable and are delivered in that order.

### REQ-7. Maintain schema and dependency evidence in Living Specs

Living Specs continuously describe the relevant table structures and dependencies so
cleanup implementations can determine ownership and safe deletion order.

**Acceptance criteria**

- The affected domain specs record table purpose, primary and identifying keys,
  relevant constraints, foreign-key direction and delete actions, and non-FK historical
  references where those references affect lifecycle behavior.
- Dependencies identify the cleanup owner, ordering or completion gate, and whether the
  referenced resource is deleted, shared, or preserved as historical evidence.
- Relationship diagrams and detailed evidence agree with current models and migrations;
  inferred implementation history is not treated as current schema authority.
- Schema or ownership changes update the relevant Living Specs in the same PR and
  include verification against the current schema.
- The initial work covers the Agent-deletion dependency boundary; maintaining the same
  documentation discipline applies to subsequent schema/dependency changes.

### REQ-8. Visible deleting and error states

An authorized viewer can recognize deletion progress and deletion errors wherever the
Agent is listed or inspected.

**Acceptance criteria**

- After deletion is accepted, the Agent has a visible deleting label in Agent lists
  and Agent detail/settings headers until its actual removal.
- An actual deletion-processing error has a distinct error label, including while
  automatic recovery is pending; normal retention or Runtime acknowledgement waits
  are not represented as failures.
- Claiming a retry alone must not misrepresent an unresolved error as recovered.
- State remains correct across refresh, revisiting the page, and multiple clients.
- Labels are localized and understandable without relying on color alone.
- Public status does not expose raw exception text, SQL, credentials, or private
  operational identifiers; existing viewing authorization remains unchanged.

### REQ-9. Read-only deleting Agents

Once deletion is accepted, the Agent stays inspectable under existing read permissions
but is read-only for user-initiated changes, including when deletion has encountered
an error.

**Acceptance criteria**

- Agent configuration and owned-resource edits, activation, new work, and interactive
  Runtime operations are unavailable; read-only navigation remains usable.
- The server enforces this boundary, including direct API requests and pages opened
  before deletion began, rather than relying only on disabled controls.
- Existing authorized cleanup, safety-stop behavior, and automatic recovery continue;
  read-only presentation must not stop the deletion pipeline.
- Repeating an already accepted DELETE retains the existing idempotent job response,
  but the UI does not present it as a new retry/cancel operation.
- No change to other Agents or shared Workspace/provider resources is implied.

## Fixed Constraints

- The emergency Runtime-history deletion fix is delivered first and independently.
- Follow current repository transaction, ownership, migration, and English artifact rules.
- Prefer existing Session lifecycle contracts where they fit; do not create a parallel
  authority for Session deletion.

## Open Assumptions

- Internal cleanup composition may change while existing public behavior stays fixed.
- The explicit deleting/error presentation and read-only behavior in REQ-8 and REQ-9
  extend the prior user-visible scope; unrelated product behavior remains unchanged.
- Exact continuation storage and code reuse are technical decisions after confirmation.

## Confirmation

The requester confirmed requirements REQ-1 through REQ-7 on 2026-10-20 (KST),
before ADR decisions and implementation of the lifecycle abstraction began.
The requester accepted the existing design direction and explicitly added REQ-8 and
REQ-9 on 2026-10-20 (KST), then approved the complete revision-2 Design and requested
implementation the same day. No additional product outcome was inferred.
