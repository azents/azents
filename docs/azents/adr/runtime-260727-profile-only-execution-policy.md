---
title: "Profile-Only Runtime Execution Policy"
created: 2026-07-27
tags: [runtime, policy, profile, admin, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260727
---

# Profile-Only Runtime Execution Policy

- Snapshot: `runtime-260727`
- Document reference: `runtime-260727/ADR`
- Requirements: [Profile-Only Runtime Execution Policy Requirements](../requirements/runtime-260727-profile-only-execution-policy.md) (`runtime-260727/REQ`)

## Context

The original hierarchy intersected a singleton Platform policy with a complete selected Profile.
This created two sources for the same authority and made saved Platform settings ineffective when
the Profile was narrower. The reserved Standard Profile compounded the problem by preventing policy
edits.

## Decision

### runtime-260727/ADR-D1: Make Profile the complete authority ceiling

Resolution begins with the selected Profile. Workspace restrictions must fit every Profile in the
Workspace allow-list, and Agent restrictions must fit the selected Profile after Workspace
restriction. There is no independent installation-wide execution-policy resource.

### runtime-260727/ADR-D2: Preserve direction-sensitive Runtime application

Profile and Workspace restrictions may automatically converge an existing Runtime. Authority
expansion remains pending until explicit Agent Apply. Agent Profile selection and override changes
remain explicit-Apply intent.

### runtime-260727/ADR-D3: Reserve identity, not policy content

`system-standard` remains non-retirable so every Workspace and Agent has a stable default identity.
Its policy and metadata are editable under optimistic concurrency and Provider-capability checks.

## Superseded Decisions

This snapshot supersedes the Platform ceiling, Platform-first resolution, immutable Standard policy,
and Platform source-version portions of `runtime-260726/ADR-D1`, `ADR-D3`, `ADR-D4`, `ADR-D6`,
`ADR-D9`, `ADR-D10`, and `ADR-D11`. All Provider enforcement, explicit expansion Apply, storage,
network, audit, and immutable snapshot decisions not contradicted here remain authoritative.

## Consequences

- Admin management contains Profiles and audit history only.
- Runtime snapshot evidence contains Profile, Workspace, and Agent source versions.
- Removing the Platform table and enum values is intentionally not API- or schema-compatible.
