---
title: "Profile-Only Runtime Execution Policy Design"
created: 2026-07-27
updated: 2026-07-27
tags: [runtime, policy, profile, admin, backend, frontend]
document_role: primary
document_type: design
snapshot_id: runtime-260727
implemented: 2026-07-27
---

# Profile-Only Runtime Execution Policy Design

- Snapshot: `runtime-260727`
- Document reference: `runtime-260727/DESIGN`
- Requirements: [Profile-Only Runtime Execution Policy Requirements](../requirements/runtime-260727-profile-only-execution-policy.md) (`runtime-260727/REQ`)
- ADR: [Profile-Only Runtime Execution Policy](../adr/runtime-260727-profile-only-execution-policy.md) (`runtime-260727/ADR`)

## Resolution

The resolver loads the selected complete Profile and initializes every governing field to the
`profile` layer. It applies the Workspace restriction and then the Agent restriction with the
existing monotone operators. New Workspace writes are validated against every Profile in the final
allow-list; new Agent writes are validated against the selected Profile after Workspace narrowing.

Stored lower-layer restrictions are applied as safe intersections even when a later Profile edit
makes their old explicit bounds broader than the new Profile. This permits Profile security
tightening to converge without turning stale lower-layer documents into resolution errors.

## Persistence and protocol

The migration removes `runtime_execution_platform_policies`,
`runtime_policy_snapshots.execution_platform_version`, the Platform management layer, and the
Platform audit event. Existing Platform audit rows are deleted before PostgreSQL enums are rebuilt.
Runtime execution evidence contains exactly `profile`, `workspace`, and `agent` source versions.

The immutable Runtime snapshot remains the application boundary. A Profile or Workspace change
that is wholly restrictive can create a new target automatically. Expansion is projected as pending
until explicit Agent Apply. An Agent setting version change blocks automatic convergence because it
represents a Profile selection or override edit.

## Admin surface

Admin Runtime Execution exposes Profiles and Audit only. Profile list responses carry the
server-owned capability gate used by the editor. The reserved Standard Profile uses the normal
replace endpoint and expected version; only retirement remains prohibited. Profile detail remains
URL-addressable through `profileId` and uses the shared responsive master-detail layout.

## Validation

- Core tests cover Profile-first resolution, lower-layer write rejection, and safe convergence of
  stale lower restrictions after Profile tightening.
- Service tests cover editable Standard policy and Workspace validation against allowed Profiles.
- Migration tests verify the new head and rendered destructive schema removal.
- Runtime Control, Provider, Runner, policy gateway, Admin Web, generated clients, and the complete
  server test suite validate the reduced source-evidence contract.
