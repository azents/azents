---
title: "Toolkit Wake-Up Snapshot Revision Design"
created: 2026-07-21
implemented: 2026-07-21
tags: [toolkit, runtime, session, backend]
document_role: primary
document_type: design
snapshot_id: toolkit-260721
---

# Toolkit Wake-Up Snapshot Revision Design

- Requirements: [toolkit-260721/REQ](../requirements/toolkit-260721-wakeup-snapshot-revision.md)
- ADR: [toolkit-260721/ADR](../adr/toolkit-260721-wakeup-snapshot-revision.md)
- Document reference: `toolkit-260721/DESIGN`

## Current Gap

`resolve_agent_tools()` creates fresh Toolkit objects for actionable Runs, but
`SessionToolkitLifecycle.reconcile()` replaces a matching desired binding with
the previously entered object solely by stable session key. The fresh resolved
object and its current config or credential state are discarded.

## Design

### Persisted revision

Add `revision` to ToolkitConfig. The migration backfills existing rows to `1`.
New ToolkitConfigs start at `1`; repository updates increment the revision in
the same SQL update that changes config or encrypted credentials.

The ToolkitConfig domain model and each DB-registered ToolkitBinding carry the
revision. No plaintext credential, ciphertext, or secret hash becomes part of
the binding identity.

### Wake-up binding snapshot

The existing actionable wake-up path continues to call `resolve_agent_tools()`.
It produces fresh bindings with stable identity and source revision before a Run
starts.

The session Toolkit lifecycle reconciles each desired binding as follows:

1. no existing stable identity: enter the new Toolkit;
2. matching identity and revision: retain the entered Toolkit instance;
3. matching identity with a different revision: enter the new Toolkit instance;
4. absent desired identity: remove the prior Toolkit instance.

The lifecycle enters every new or replacement instance first. It closes replaced
and removed instances only after all requested entries succeed. On failure it
closes only newly entered instances and preserves the prior snapshot.

### Non-persisted Toolkit bindings

Auto-bound Toolkit bindings receive a stable revision derived from their
non-secret source configuration. Their membership remains determined by the
fresh wake-up resolve result. Existing actor-specific session keys continue to
prevent cross-user reuse.

Provider-owned ephemeral tokens continue to refresh in the provider without
forcing a persisted ToolkitConfig revision update.

## Traceability

| Requirement | ADR decision | Design mechanism |
| --- | --- | --- |
| toolkit-260721/REQ-1 | ADR-D1, ADR-D3 | ToolkitConfig revision migration and atomic repository increments |
| toolkit-260721/REQ-2 | ADR-D2 | Revision-bearing bindings and lifecycle replacement |
| toolkit-260721/REQ-3 | ADR-D2 | Enter-before-close reconciliation |
| toolkit-260721/REQ-4 | ADR-D1, ADR-D3 | Opaque ID/revision comparison with no secret material |

## Failure Handling

- A failed new or replacement Toolkit entry rolls back only the entries created
  for that wake-up.
- Existing entered Toolkit instances remain available after a failed
  reconciliation.
- A Toolkit source update becomes visible only at the next actionable wake-up;
  an active Run keeps its initial snapshot.

## Test Strategy

### Primary verification matrix

| Scenario | Expected result |
| --- | --- |
| Unchanged ToolkitConfig revision | Existing session instance is reused |
| ToolkitConfig revision update | Fresh instance replaces the existing instance |
| Credential-only update | Revision increments and fresh instance replaces existing one |
| Attach or detach | Next snapshot enters or closes the affected instance |
| Replacement entry failure | New entries close and previous snapshot remains active |
| EnvVar update | Next actionable wake-up shell environment uses the updated value |

### Verification plan

- Add repository tests for revision initialization and increment paths.
- Add session lifecycle tests for equal-revision reuse, changed-revision
  replacement, and failure rollback.
- Run backend Ruff, Pyright, targeted tests, and the full backend test suite.

No external credential or testenv fixture is required because the behavior is
covered by deterministic Toolkit lifecycle tests.
