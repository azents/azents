---
title: "Safe Runtime Operation Admission Requirements"
created: 2026-10-26
tags: [runtime, reliability, backend]
document_role: primary
document_type: requirements
snapshot_id: runtime-261026
---

# Safe Runtime Operation Admission Requirements

- Snapshot: `runtime-261026`
- Document reference: `runtime-261026/REQ`

## Problem

A Runtime tool invocation can reject the normal first-start transition as an unexpected configuration change. A brief Control connection replacement can also expose a transient failure before an operation is accepted. Retrying every failure indiscriminately could execute a mutation more than once or bypass a genuine authority change.

## Primary Context

### Primary System Outcome

An eligible Runtime operation proceeds through an ordinary automatic start or a brief pre-submission Control reconnection without requiring an Agent retry, while preserving configuration authority and preventing automatic replay of accepted or uncertain submissions.

## Supporting Scenarios or Effects

- Concurrent Sessions may request the same Agent's first Runtime use.
- Runtime configuration, capability, or lifecycle authority may change while an operation waits.
- Control may reconnect while the physical Runtime remains alive.
- A prolonged outage or cancellation must terminate the wait without launching work later.

## Goals

- Handle an authorized ordinary automatic start without treating that transition alone as an unrelated configuration change.
- Absorb brief pre-submission transport unavailability within a finite operation budget.
- Preserve existing authorization, generation fencing, retained applied-configuration behavior, and no-replay safety.

## Non-Goals

- Session working-folder creation, binding, naming, or default-directory changes; those are separate work.
- Uninterrupted completion or cross-generation resumption of operations already submitted before connection loss.
- Transparent retries of browser actions, process input, patches, transfers, or other effects after acceptance or ambiguous submission.
- Runtime replacement, restart, reset, profile fallback, Provider failover, or migration to another configuration as outage recovery.
- New user-facing Runtime settings, persistent operation histories, or broad deployment/HA redesign.
- Production deployment or automatic PR merge. Implementation and PR preparation are authorized after technical Design approval.

## Requirements

### REQ-1. Normal automatic start remains within the original invocation

An operation eligible under the current Runtime authority must not fail solely because the ordinary automatic start it requires advances lifecycle/configuration identity.

**Acceptance criteria**

- A stopped, valid managed Runtime can become ready and receive the original operation once without a model-level retry.
- Concurrent first-use callers cannot create extra start transitions or submit the same caller's operation twice.
- A Runtime that cannot start under its actual current configuration remains a failure rather than silently selecting another configuration.

### REQ-2. Genuine authority changes remain fenced

Automatic-start handling must not authorize work under unrelated or superseding authority.

**Acceptance criteria**

- Capability removal, explicit stop/reset/recreation, or a configuration replacement that invalidates the operation's selected authority prevents submission.
- The existing permission to use a valid retained applied configuration remains unchanged; a change to a future desired configuration alone does not revoke that existing authority.
- A reconnect alone does not change selected configuration authority or authorize migration to another physical Runtime lifecycle.

### REQ-3. Brief pre-submission connection loss is absorbed safely

When authoritative evidence establishes that an operation was not accepted, a brief Control/Runner reconnect may be waited out within the same invocation.

**Acceptance criteria**

- Reconnection before acceptance can result in one successful submission without surfacing an intermediate transient failure to the model.
- Authority is revalidated before submission after the wait.
- An accepted request or ambiguous submission is never automatically resubmitted, including under a new Runner connection generation.
- Existing exact-request result observation may continue where already supported; this requirement does not introduce cross-generation operation recovery.

### REQ-4. Waiting is bounded and outcomes are truthful

Connection waiting does not permit indefinite work or speculative success.

**Acceptance criteria**

- The invocation has a finite overall budget that is not reset by each reconnect or admission attempt.
- Cancellation, revoked authority, and terminal Runtime failure end waiting and do not leave a later submission scheduled.
- Exhausted pre-submission waiting is distinguishable from a submitted operation whose completion is unknown.
- No timeout or connection loss is reported as successful execution.

## Fixed Constraints

- Reuse the existing Runtime authority, lifecycle, and operation coordination ownership boundaries unless a later accepted technical decision explicitly changes them.
- Preserve generation fencing, current Runner-reported Workspace authority, and existing at-most-once/no-replay behavior.
- Correctness must not require Redis availability, persistence, or HA; supported coordination backends must preserve equivalent safety.
- Do not add credentials, command contents, patch contents, or other sensitive payloads to diagnostic logs.
- Keep Session working-folder changes outside this snapshot.

## Open Assumptions

- The finite timing policy and exact admission boundaries will be selected during technical design, not by adding a new user-facing option here.
- Outages exceeding the operation budget remain explicit failures; seamless handling of in-flight work is intentionally not promised.

## Confirmation

Confirmed by the requester on 2026-10-26. The requester approved the presented requirements and recommended direction, delegated remaining bounded technical decisions, and requested implementation through a pull request. Production deployment and PR merge remain outside this authorization.
