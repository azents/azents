---
title: "Toolkit Wake-Up Snapshot Revision Requirements"
created: 2026-07-21
updated: 2026-07-21
implemented: 2026-07-21
tags: [toolkit, runtime, session, security]
document_role: primary
document_type: requirements
snapshot_id: toolkit-260721
---

# Toolkit Wake-Up Snapshot Revision Requirements

- Snapshot: `toolkit-260721`
- Document reference: `toolkit-260721/REQ`

## Problem

AgentSession runners resolve the current Toolkit configuration for a new Run, but
session-managed Toolkit instances can retain an earlier resolved state. A manager
cannot rely on a Toolkit config or credential change taking effect for the next
actionable session wake-up.

## Primary Actor

Workspace manager who updates a Toolkit configuration or credential used by an
active AgentSession.

## Primary Scenario

After the workspace manager changes a Toolkit configuration or credential, the
next actionable SessionWakeUp for an attached Agent resolves and executes with
the changed Toolkit state without requiring a worker restart or a new session.

## Supporting Scenarios

- An unchanged Toolkit retains its active session instance and connection state.
- Attaching, detaching, enabling, or disabling a Toolkit changes the next
  actionable wake-up snapshot.
- A failed replacement leaves the previously active Toolkit snapshot usable.

## Goals

- Make the latest persisted Toolkit source state authoritative at each actionable
  SessionWakeUp.
- Replace only Toolkit instances whose persisted source revision changed.
- Preserve unchanged stateful Toolkit connections between wake-ups.
- Avoid exposing plaintext credentials through revisions, snapshot comparison, or
  logging.

## Non-Goals

- Reloading Toolkit configuration in the middle of an active Run.
- Querying the database for every individual tool call or shell command.
- Preserving compatibility with a session-pinned stale Toolkit configuration.

## Requirements

### REQ-1. Revisioned Toolkit source

Each ToolkitConfig must have a monotonically increasing persisted revision.

**Acceptance criteria**

- A newly created ToolkitConfig starts at revision `1`.
- Updating config, credentials, prompt, name, slug, description, or enabled state
  increments the revision exactly once.
- The revision is available to Run-time Toolkit resolution without decrypting or
  exposing credential values.

### REQ-2. Wake-up snapshot reconciliation

Each actionable SessionWakeUp must resolve the attached Toolkit source state and
use its resulting snapshot for the Run.

**Acceptance criteria**

- A ToolkitConfig revision change replaces the corresponding session-managed
  Toolkit instance before the Run starts.
- An attached Toolkit whose revision did not change retains its existing
  session-managed instance.
- Attaching, detaching, enabling, or disabling a Toolkit changes the next
  actionable wake-up Toolkit snapshot.

### REQ-3. Atomic replacement

Toolkit replacement must not leave a session without its last known-good
Toolkit instance when preparation of the new snapshot fails.

**Acceptance criteria**

- New or replacement Toolkit instances enter successfully before replaced
  instances are closed.
- If entering any new or replacement Toolkit fails, all newly entered instances
  are closed and the prior session snapshot remains active.

### REQ-4. Credential confidentiality

Snapshot identity and operational logs must not contain plaintext credentials or
credential-derived hashes.

**Acceptance criteria**

- Snapshot comparison uses ToolkitConfig identity, persisted revision, and
  non-secret execution context only.
- Logs and test assertions do not print credential values.

## Fixed Constraints

- The policy applies uniformly to all session-managed Toolkit bindings.
- A Run uses one fixed Toolkit snapshot from its start through completion.
- Existing long-lived Toolkit instances remain reusable only when their source
  snapshot is unchanged.

## Open Assumptions

- Provider-owned short-lived token refresh remains inside the relevant Toolkit and
  does not require a ToolkitConfig revision change.

## Confirmation

Confirmed by the requester on 2026-07-21 before ADR and design decisions began.
