---
title: "Provider Infrastructure Profile Deletion"
created: 2026-08-11
tags: [admin, runtime, provider, infrastructure-profile, deletion, architecture]
document_role: primary
document_type: adr
snapshot_id: provider-260811
---

# Provider Infrastructure Profile Deletion

- Snapshot: `provider-260811`
- Document reference: `provider-260811/ADR`
- Requirements: [Provider Infrastructure Profile Deletion Requirements](../requirements/provider-260811-infrastructure-profile-deletion.md) (`provider-260811/REQ`)

## Decision Map

- [x] `provider-260811/ADR-D1` — Terminate active infrastructure-Profile recreation when its target is deleted.
- [x] `provider-260811/ADR-D2` — Provide System-Admin-owned read-only Workspace Runtime Profile detail.

## Fixed or Derived Outcomes

The confirmed Requirements already determine these outcomes and this ADR does not reopen them:

- Only current Workspace Runtime Profile references block deletion.
- Applied-only running Runtime usage is warning information and does not block deletion.
- Deletion is System-Admin-only, exact-Provider-scoped, exact-version-fenced, and atomically rechecks current references.
- A successful operation hard-deletes only the selected infrastructure Profile and creates no fallback, alias, tombstone, or replacement.
- Provider capability state, Workspace Runtime Profiles, Workspace defaults, Agent selections, Runtime desired and applied configuration, Provider bindings, running workloads, Runner Workspace paths, and Agent Workspace storage are not changed by deletion.
- Deleted display names become reusable.
- The Admin flow performs a fresh impact read, exposes bounded current-reference information and applied-only warning information, and fails closed when that read is unavailable.

## Agent-Owned Design Details

The Design will select conventional API paths and methods, response field names, repository helper boundaries, SQL query composition, pagination bounds, frontend component boundaries, responsive layout details, cache invalidation, generated-client wiring, fixtures, and test file placement. These choices may not introduce another authority, lifecycle mode, fallback, or user-visible behavior.

## Context

Provider-owned infrastructure Profiles are mutable exact-Provider resources. A Workspace Runtime Profile currently holds a restrictive foreign-key reference to one infrastructure Profile. Runtime desired and applied configuration documents retain scalar Profile identity and version evidence rather than foreign keys, so applied-only evidence can survive hard deletion without preserving the mutable Profile resource.

The Admin API and UI support Profile creation, replacement, compatibility inspection, and Provider- or Profile-scoped Runtime recreation, but they expose no Profile deletion or deletion-impact contract. Infrastructure-Profile recreation operations are durable, version-snapshotted work that may still be pending or running when Workspace authority moves away from the target. The reconciler normally skips an item when the target disappears or changes, but deletion needs one explicit terminal operational boundary so no later worker can dispatch new recreation from deleted authority.

The current Admin application lists Workspaces but does not expose a System-Admin-readable Workspace Runtime Profile detail destination. The customer Workspace settings surface is membership-authorized and therefore cannot automatically serve as cross-Workspace System Admin navigation authority.

## Decisions

### provider-260811/ADR-D1: Terminate active infrastructure-Profile recreation when its target is deleted

**Affected requirements:** `provider-260811/REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`

The authoritative delete transaction completes every pending or running recreation
operation targeted directly at the infrastructure Profile. Items that have not
reached a confirmed terminal result are marked skipped with bounded
`target_deleted` evidence, and the operation is completed. No worker may dispatch a
new Runtime restart from that deleted target after the transaction commits.

A lifecycle command already delivered to a Provider before deletion is not
cancelled or rolled back. Deletion does not create authority to reverse an
in-flight backend mutation, and the Runtime continues through ordinary
generation-fenced lifecycle observation. The operation record remains bounded
historical outcome evidence rather than authority to resume work.

This matches the established Workspace Runtime Profile deletion boundary while
preserving the stricter requirement that infrastructure Profile deletion itself
must not schedule or initiate Runtime lifecycle work.

### provider-260811/ADR-D2: Provide System-Admin-owned read-only Workspace Runtime Profile detail

**Affected requirements:** `provider-260811/REQ-2`, `REQ-3`, `REQ-8`

The reference list navigates to a System-Admin-owned read-only Workspace Runtime
Profile detail context in the Admin application. Access requires System Admin
authority and does not require Workspace membership.

The detail context may expose the Workspace identity, exact Workspace Runtime
Profile document, selected Provider and infrastructure Profile identities,
lifecycle and version, current Agent selection count, and current running Runtime
count. It does not grant Workspace Owner or Manager mutation authority and does not
proxy customer-surface write actions.

System Admin authority and Workspace membership remain separate. The link does not
target the customer Workspace settings page because a System Administrator may
legitimately need to inspect a blocking reference without belonging to that
Workspace.

## Rejected Alternatives

### Continue target-scoped recreation after Profile deletion

Rejected because it would permit new Runtime restarts to be dispatched from an
absent Profile after deletion. A pre-delete snapshot remains historical evidence,
not continuing lifecycle authority.

### Cancel or roll back an already dispatched Runtime restart

Rejected because deletion cannot reliably revoke a command already delivered to an
external Provider, and compensating lifecycle work would violate the no-disruption
boundary.

### Navigate to the customer Workspace Runtime Profile settings page

Rejected because System Admin authority does not imply Workspace membership. Using
the customer route would make a required Admin inspection path inaccessible or
would improperly merge instance-wide and Workspace-scoped authority.

## Consequences

- Deletion has a durable terminal boundary for target-scoped recreation and cannot
  leave resumable work authorized by an absent Profile.
- An already delivered restart may settle after deletion, but deletion performs no
  cancellation, rollback, or compensating Runtime operation.
- Recreation outcome projections can distinguish target deletion from ordinary
  Runtime failure.
- System Administrators can inspect blocking Workspace Runtime Profiles without
  receiving Workspace mutation authority.
- The Admin application and API gain a bounded cross-Workspace read projection,
  while customer Workspace authorization remains unchanged.
