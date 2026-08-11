---
title: "Runtime Profile Deletion Design"
created: 2026-08-11
updated: 2026-08-11
implemented: 2026-08-11
tags: [runtime, profile, workspace, persistence, architecture]
document_role: primary
document_type: design
snapshot_id: profile-260811
---

# Runtime Profile Deletion Design

- Snapshot: `profile-260811`
- Document reference: `profile-260811/DESIGN`
- Requirements: [Runtime Profile Deletion Requirements](../requirements/profile-260811-runtime-profile-deletion.md) (`profile-260811/REQ`)
- ADR: [Runtime Profile Deletion](../adr/profile-260811-runtime-profile-deletion.md) (`profile-260811/ADR`)

## Current Behavior and Gaps

Workspace Runtime Profiles support create, replace, list, get, default selection, and scoped Runtime recreation, but no permanent deletion. Current references from Workspace default selection, Agent selection, Agent Runtime desired binding, Runtime configuration revisions, Runtime recreation items, and Agent Runtime addition receipts prevent physical deletion.

Each resolved target creates or reuses an immutable `runtime_configuration_revisions` row. Agent Runtime stores desired and applied revision foreign keys. Provider and Runner reports echo the revision ID with digest and desired generation, and exact equality promotes the desired revision to applied. Lifecycle generation changes may clone a usable revision into a new target generation. Runtime recreation items and addition receipts also retain revision foreign keys.

Repository inspection found 40 active source, migration, test, and UI files coupled directly to Runtime configuration revisions. A read-only production snapshot on 2026-08-11 contained 3 Workspace Runtime Profiles, 6 managed Runtimes, and 205 configuration revisions. Of those revisions, 159 were not referenced by current desired, current applied, or recreation-item authority; one Runtime had 56 revisions. This confirms that the persisted revision set materially exceeds current Runtime configuration needs.

The gaps against `profile-260811/REQ` are:

1. Profile deletion is blocked by current and historical foreign keys;
2. stale desired and applied configuration documents accumulate indefinitely;
3. revision UUIDs conflate freshness fencing with permanent persisted identity;
4. revision-shaped API and UI contracts expose history the product does not need; and
5. deletion of a selected Profile has no atomic current-state transition.

## Design Overview

Runtime configuration becomes bounded current state. Each Agent Runtime owns one one-to-one `runtime_configuration_states` row containing a desired slot and an applied slot. Agent Runtime owns a monotonic configuration-sequence high-water mark that survives terminal cleanup and Runtime rearm. New targets overwrite desired state; exact promotion overwrites applied state; terminal deletion removes both documents.

Workspace Runtime Profile deletion is a PostgreSQL transaction that clears a matching Workspace default and Agent selections, writes affected Runtime desired state as unconfigured, supersedes Profile-targeted recreation, and deletes the Profile row. Existing applied state remains while its physical Runtime remains current. There is no Profile tombstone and no configuration revision history.

## Ownership and Source of Truth

- `workspace_runtime_profiles` remains the source of truth only for existing selectable Profiles.
- `agents.runtime_profile_id` remains the source of truth for current Agent selection.
- `agent_runtimes` remains the source of truth for logical Runtime lifecycle, Provider routing, desired generation, connection generations, and the monotonic configuration-sequence high-water mark.
- `runtime_configuration_states` becomes the source of truth for the current desired and applied configuration slots.
- PostgreSQL reconciliation and recreation tasks remain durable work authority; Redis remains optional delivery acceleration only.
- Provider and Runner reports remain observations that can acknowledge only the exact current configuration tuple.

## Data Model

### Agent Runtime sequence authority

`agent_runtimes` adds:

```text
configuration_sequence BIGINT NOT NULL DEFAULT 0
```

This is a monotonic high-water mark. It is incremented under the Runtime row lock whenever a materially new desired target is committed, including a new lifecycle desired generation, Profile/source change, blocked target, or transition to unconfigured state. It is not reset by terminal deletion or Runtime rearm. Deleting the Agent Runtime removes the high-water mark.

The following duplicate desired-source and revision-pointer columns are removed from `agent_runtimes`:

```text
infrastructure_profile_id
workspace_runtime_profile_id
desired_runtime_configuration_revision_id
applied_runtime_configuration_revision_id
```

Provider logical/resource binding remains on Agent Runtime because a running Runtime must remain routable after its Profile is deleted.

### Runtime configuration state

One row exists per Runtime only while desired or applied configuration state exists:

```text
runtime_configuration_states
  runtime_id PK FK agent_runtimes.id ON DELETE CASCADE

  desired_sequence BIGINT NOT NULL
  desired_status ENUM(unconfigured, blocked, ready) NOT NULL
  desired_target_generation BIGINT NOT NULL
  desired_digest VARCHAR(64) NULL
  desired_document JSONB NULL
  desired_reason_code VARCHAR(120) NULL
  provider_reported_digest VARCHAR(64) NULL
  runner_reported_digest VARCHAR(64) NULL
  provider_acknowledged_at TIMESTAMPTZ NULL
  runner_observed_at TIMESTAMPTZ NULL

  applied_sequence BIGINT NULL
  applied_target_generation BIGINT NULL
  applied_digest VARCHAR(64) NULL
  applied_document JSONB NULL
  applied_at TIMESTAMPTZ NULL

  created_at TIMESTAMPTZ NOT NULL
  updated_at TIMESTAMPTZ NOT NULL
```

`desired_document` and `applied_document` use one canonical schema-versioned configuration-state envelope decoded into a typed domain payload at repository ingress. The envelope contains the existing source trace, Provider aggregate and capability identity, infrastructure Profile ID/version, Workspace Profile ID/version, Agent selection version, required/missing capability evidence, and resolved configuration. It contains no credential or raw Provider authentication material.

A ready desired slot requires digest and a resolved document and has no reason. A blocked desired slot requires a bounded reason and may retain source evidence but no resolved configuration. An unconfigured desired slot has reason `runtime_profile_required`, no selected Profile authority, and no resolved configuration. Applied state is always a ready canonical document.

Profile, infrastructure Profile, and capability identifiers inside current-state documents are snapshot scalars, not foreign keys. Current state must not prevent deletion of the mutable source entity that produced it.

### Runtime addition receipts

`agent_runtime_add_receipts` replaces `runtime_configuration_revision_id` with:

```text
runtime_configuration_sequence BIGINT
runtime_configuration_digest VARCHAR(64)
runtime_desired_generation BIGINT
```

Its `workspace_runtime_profile_id` remains exact idempotency request evidence but loses its foreign key to the mutable Profile. Replays first validate current Agent capability and selection versions; a deleted or replaced selection makes the receipt stale without dereferencing the former Profile.

### Recreation items

`runtime_recreation_operation_items` replaces `expected_configuration_revision_id` with:

```text
expected_configuration_sequence BIGINT
expected_configuration_digest VARCHAR(64)
expected_desired_generation BIGINT
```

Dispatch and completion compare this tuple against current Runtime configuration state. Completed operation metadata follows existing retention and does not retain full configuration documents.

## Configuration State Transitions

### Resolve or reconcile desired state

Resolution reads one exact Agent selection, Profile, infrastructure Profile, Provider capability, and Runtime desired generation snapshot. Under final CAS it locks the Agent Runtime, verifies those sources are still current, increments `configuration_sequence`, and overwrites the desired slot.

If the canonical target tuple and target generation already equal current desired state, resolution returns the existing state without incrementing the sequence. A source change that resolves to the same digest still increments the sequence when its authority version changed.

Writing desired state clears Provider and Runner acknowledgement fields. The previous desired document is removed in the same update.

### Lifecycle generation advance

Create, start, restart, reset, and recreate require a ready current target. The lifecycle command locks Agent Runtime and configuration state, verifies the expected sequence/digest/generation tuple, advances `desired_generation`, increments `configuration_sequence`, and retargets the same ready document to the new desired generation. This replaces revision cloning.

### Provider acknowledgement

A Provider acknowledgement updates the desired slot only when authenticated Runtime identity, Provider aggregate, Provider connection generation, desired generation, configuration sequence, and digest match current state. Stale acknowledgement is ignored or produces the existing bounded mismatch result.

### Runner acknowledgement and applied promotion

Runner evidence is admitted only for the authenticated Runtime and current Runner generation. When both Provider and Runner evidence match the current ready desired tuple, one CAS copies the desired tuple and document into applied state. The previous applied document is overwritten in that transaction.

Reports matching current applied state remain acceptable for a healthy running Runtime while desired state is blocked or unconfigured after Profile deletion.

### Terminal deletion and rearm

Exact terminal deletion acknowledgement deletes the Runtime configuration-state row. Agent Runtime retains only the monotonic high-water mark and terminal lifecycle evidence. Rearm creates a new state row and allocates the next sequence, so evidence from a prior incarnation cannot become current.

## Runtime Profile Hard Delete

### API

Add:

```text
DELETE /runtime-profile/v1/workspaces/{handle}/profiles/{profile_id}
```

The request requires `expected_version`. The response is `200` with:

```text
profile_id
cleared_workspace_default
cleared_agent_count
affected_running_runtime_count
superseded_recreation_operation_count
```

A second request returns `runtime_profile_not_found`. Cross-Workspace identifiers remain indistinguishable from not found. Stale version returns `runtime_profile_version_conflict`.

### Permission

Add `WorkspacePermission.RUNTIME_PROFILES_DELETE`. Only Workspace Owner receives this permission. Existing read/write permissions remain unchanged for Managers and Owners.

### Transaction

The service performs one transaction:

1. resolve Workspace membership and require delete permission;
2. lock Workspace and target Profile and validate ownership/version;
3. clear a matching Workspace default and advance its default version;
4. lock and clear every matching Agent selection and advance each selection version;
5. allocate a new configuration sequence for every affected managed Runtime and overwrite desired state as `unconfigured/runtime_profile_required`;
6. supersede pending or running recreation operations targeting the deleted Profile and terminalize undispatched items as `target_deleted`;
7. let older Profile-source reconciliation tasks become stale and enqueue current Agent-selection tasks only where other projection work remains necessary;
8. delete the Profile row;
9. emit one bounded deletion event with identifiers, actor, version, and impact counts; and
10. commit.

The Profile row lock and retained live-selection foreign keys serialize concurrent selection against deletion. Integrity conflicts are translated to one bounded conflict result; no retry path chooses a fallback Profile.

### Runtime behavior after deletion

A running Runtime keeps its applied slot and Provider binding. Its public configuration status becomes `profile_required`; create/start/restart/reset/recreate and Runner-dependent actions are unavailable. Stop, observe, and terminal removal remain available where current lifecycle authority permits them.

Selecting a replacement Profile writes a new ready desired slot with a higher configuration sequence. Recreation preserves Agent Workspace storage. Exact promotion replaces the former applied slot and removes the deleted Profile's remaining configuration document.

## Protocol and Operation Authority

`RuntimeConfigurationEvidence` changes conceptually from revision identity to sequence identity:

```text
configuration_sequence
digest
desired_generation
```

The protobuf keeps field number and wire type for the first string field while renaming it from `revision_id` to `configuration_sequence`. The value is the canonical decimal representation of a positive sequence. This permits already running older Runner binaries that treat field 1 as opaque evidence to echo the new value during the coordinated rollout, without retaining a server-side revision alias or legacy acceptance branch.

Server-side and newly built Provider/Runner validation rejects non-canonical sequence text. Current Provider protocol version admission remains exact. Runtime operation authority, Session worktree routing, built-in Runtime tools, transfer readiness, and Runner operation targets replace revision ID with configuration sequence plus digest and desired generation.

## Reconciliation and Recreation

Profile, infrastructure Profile, Provider capability, and Agent selection source-version tasks remain durable and bounded. Their work result is a current desired-slot overwrite rather than revision creation. A missing deleted source marks older source tasks stale.

Recreation operations snapshot target version as today. Per-Runtime items additionally snapshot expected configuration sequence/digest/desired generation. If current desired state changes before dispatch, the item is skipped as superseded. If current applied state already matches the tuple, the item completes without another recreation.

Profile hard deletion supersedes active operations whose target is the Profile. Operation reads use stored Workspace ownership and target snapshot metadata rather than requiring the deleted Profile row to exist.

## Migration

A forward migration performs these steps in one coordinated control-plane cutover:

1. add `agent_runtimes.configuration_sequence`;
2. create `runtime_configuration_states`;
3. add sequence/digest fields to Runtime addition receipts and recreation items;
4. backfill only current desired/applied pointers;
5. assign sequence `1` when desired and applied share one revision, or ordered sequences when they differ;
6. copy current acknowledgement and resolved/source evidence into desired/applied slots;
7. copy active receipt and recreation fencing to sequence/digest/generation fields;
8. verify every non-null current pointer and active operation item was converted;
9. remove revision foreign keys and direct desired-source columns from Agent Runtime;
10. remove revision fields from receipts and recreation items; and
11. drop `runtime_configuration_revisions`, deleting every stale historical row.

Completed historical revisions that are not current authority are intentionally not migrated. A migration preflight fails if a current pointer references a missing or cross-Runtime revision, if a ready revision lacks a valid resolved document/digest, or if active operation evidence cannot be converted.

Downgrade reconstructs at most the current desired and applied revision rows per Runtime from current-state slots, assigns new revision IDs, and restores pointers. It does not reconstruct superseded history. Downgrade after a later Profile hard delete may restore only current configuration evidence and cannot restore deleted Profiles.

## Rollout

Runtime configuration writers are quiesced during the schema authority cutover so old and new control-plane writers cannot diverge. The migration and new server/control components are deployed as one coordinated release. Existing physical Runtimes continue running during the bounded transport disconnect.

The new server emits decimal configuration sequence through protobuf field 1. Existing Runner and Provider clients that treat the field as an opaque string can echo it. Current protocol-version admission still rejects obsolete Provider protocol versions, and there is no legacy product mode. Updated Provider and Runner images adopt the renamed generated field in the same release family.

After rollout, Runtime Control re-observes current Provider and Runner evidence. A healthy Runtime whose current applied document and generations match becomes available without a user restart, preserving the existing deployment-continuity contract.

## Failure, Retry, and Recovery

- Failed desired-state calculation leaves the prior transaction unchanged and enqueues bounded reconciliation retry.
- A blocked calculation overwrites desired state with bounded reason and retains applied state.
- Stale Provider/Runner evidence cannot update acknowledgement or applied state.
- Profile deletion failure rolls back the default, Agent selections, desired-state updates, operation supersession, and row deletion together.
- A deleted Profile never reappears through retry; recovery requires creating or selecting a new Profile.
- Failed replacement recreation retains prior applied state and Agent Workspace storage.
- Terminal deletion remains the authority that removes final configuration documents for an unreplaced Runtime.

## API, Generated Clients, and UI

Public OpenAPI replaces revision response models with current configuration-state models exposing status, sequence, target generation, digest, bounded source metadata, and acknowledgement times. Raw resolved configuration remains excluded from ordinary customer status responses where the current contract excludes it.

The Web Runtime Profile page adds an owner-only permanent delete action, impact confirmation, Profile-name confirmation, and result feedback. Runtime status replaces desired/applied revision labels with desired/applied configuration sequence. A deleted selection shows `Runtime Profile required`; technical details may show the current applied sequence and source identifier while the old physical Runtime remains.

Official Public Python and TypeScript clients are regenerated. Admin API changes are limited to shared generated types unless an Admin hard-delete surface is separately required.

## Observability

Profile deletion logs and events contain Profile ID, Workspace ID, version, actor ID, and bounded impact counts, but no Profile policy or resolved Runtime configuration document. Configuration-state diagnostics contain sequence, digest, desired generation, Provider/Runner generations, status, and bounded reason code.

Metrics cover deletion success/conflict, affected Agent count, configuration-state transitions, stale evidence rejection, desired-to-applied latency, and migration preflight failures. No metric label contains unbounded Profile names or configuration documents.

## Test Strategy

### E2E primary matrix

1. Create a Profile, set it as Workspace default, select it for multiple Agents, and create a running Docker Runtime.
2. Hard delete the Profile as Workspace Owner.
3. Verify Profile list/get absence, default and Agent selection clearing, no fallback, running Runtime continuity, preserved Agent Workspace, blocked configuration-requiring actions, and allowed stop/removal.
4. Select a replacement Profile, recreate, and verify exact new applied sequence plus absence of the former applied document.
5. Exercise A-to-B-to-A desired changes and prove late acknowledgement from the first A cannot promote the third target.
6. Terminally delete a Runtime and verify configuration-state document removal while the sequence high-water remains fenced for rearm.

### Focused verification

- Migration converts only current desired/applied authority and removes all stale revisions.
- Current production-shape fixtures include desired-only, applied-only, shared desired/applied, divergent desired/applied, blocked desired, active recreation, and addition receipt cases.
- Repository CAS tests cover source drift, desired-generation changes, sequence races, Provider/Runner mismatch, promotion, and terminal cleanup.
- Permission tests prove Owner-only deletion and cross-Workspace not-found behavior.
- Protocol tests prove field-1 opaque-wire continuity and canonical sequence validation.
- API/OpenAPI/generated-client tests contain no Runtime configuration revision models.
- UI tests cover impact confirmation, successful deletion, stale version conflict, and deleted-selection recovery.
- Repository-wide absence checks allow historical snapshot documents but find no active `RuntimeConfigurationRevision`, revision table, desired/applied revision pointer, expected revision FK, or Runtime revision UI terminology.

The Docker-backed Runtime Profile journey is required CI evidence. Kubernetes coverage reuses the same server-side state tests and adds a qualified lifecycle continuity journey where the existing lane is available. Missing required Docker prerequisites fail; optional live Kubernetes prerequisites follow the existing qualified skip/fail policy.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Permanently delete Workspace Runtime Profile rows and clear current default and Agent selections without fallback | `profile-260811/REQ-1`, `REQ-2`; `profile-260811/ADR-D3` | `required` |
| M2 | Replace historical revisions with one desired/applied current-state row per Runtime and a Runtime-owned sequence high-water mark | `profile-260811/REQ-4`, `REQ-6`; `profile-260811/ADR-D1` | `decided` |
| M3 | Fence Provider, Runner, lifecycle, recreation, and operation authority by sequence, digest, desired generation, and connection generation | `profile-260811/REQ-5`; `profile-260811/ADR-D2`; current Runtime Control generation fencing | `decided` |
| M4 | Preserve an already running Runtime and applied state until exact replacement or terminal deletion | `profile-260811/REQ-3`, `REQ-6`, `REQ-8`; `profile-260811/ADR-D4`; current Workspace-preserving Runtime lifecycle | `decided` |
| M5 | Make deletion Owner-only and atomically authoritative in PostgreSQL | `profile-260811/REQ-7`; `profile-260811/ADR-D5` | `decided` |
| M6 | Replace revision-shaped API, protobuf, receipt, operation, generated-client, and UI contracts without a legacy mode | `profile-260811/REQ-4`, `REQ-5`; `profile-260811/ADR-D6` | `decided` |
| M7 | Migrate only current desired/applied authority and delete superseded revision data | `profile-260811/REQ-4`, `REQ-6`; M2, M3 | `derived` |
| M8 | Recover through explicit replacement Profile selection and storage-preserving Runtime recreation | `profile-260811/REQ-8`; M1, M4 | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| `runtime_configuration_revisions` table and ORM/domain models | M2, M7 | One current `runtime_configuration_states` row | DB schema, repository, services, tests | Schema introspection and active-code absence search |
| Agent Runtime desired/applied revision pointers and direct desired Profile fields | M2 | Configuration state slots and sequence high-water | Agent Runtime model/repository/API | Model and OpenAPI absence checks |
| Revision creation, clone, acknowledgement, equality, and promotion repository methods | M2, M3 | Current-state CAS operations | Runtime Profile and Agent Runtime repositories | Focused repository tests and symbol absence |
| `expected_configuration_revision_id` recreation authority | M3, M6 | Expected sequence/digest/desired generation | Recreation model/service/API/tests | Migration and recreation E2E |
| Agent Runtime add receipt revision/Profile foreign keys | M1, M3, M6 | Scalar request identity plus sequence/digest/generation receipt | Add receipt model/service/tests | Replay and Profile deletion tests |
| Protobuf and shared-client `revision_id` terminology | M3, M6 | Canonical decimal configuration sequence on the existing wire field number | Proto, generated modules, clients, servers | Cross-version wire and current-version validation tests |
| Public revision status models and web revision labels | M6 | Desired/applied current configuration status and sequence | API, OpenAPI, generated clients, web | Generated-schema and UI absence checks |
| Permanent stale configuration history | `profile-260811/REQ-4`, `REQ-6` | None | Migration and lifecycle cleanup | DB assertion that state rows are bounded per Runtime |
| Profile disable/archive as deletion substitute | `profile-260811/REQ-1`; `profile-260811/ADR-D3` | Permanent owner deletion while ordinary disable remains availability control | Workspace Profile API/UI | Hard-delete E2E and row absence |
| Earlier implemented Runtime Profile snapshot documents | `profile-260811/REQ` fixed constraint | Immutable historical records | None; retained | Documents remain unchanged |

## Feasibility

- M1: feasible. Live Profile references are repository-local. Workspace default and Agent selection can be cleared set-wise under the Profile lock. Current production maximum was three selected Agents for one Profile, while the transaction remains defined without a product cardinality limit.
- M2: feasible. Current revision documents already contain the complete desired/applied source, resolution, digest, and acknowledgement state required for backfill. Production contained 205 revisions for six Runtimes, with 159 noncurrent rows, demonstrating direct cleanup value.
- M3: feasible. Current Provider and Runner messages already carry revision identity, digest, and desired generation as opaque evidence. A monotonic sequence replaces the identity without weakening A-to-B-to-A fencing.
- M4: feasible. Current state sinks already accept exact applied evidence separately from pending desired evidence, and current lifecycle projections can block configuration-requiring actions while preserving stop and terminal deletion.
- M5: feasible. Existing Workspace permission resolution can add a distinct delete action; PostgreSQL remains the only correctness authority.
- M6: feasible but broad. Forty active files directly reference Runtime configuration revisions, including API, repositories, Runtime Control, transitions, recreation, receipts, tests, and Web. The replacement boundary is explicit and repository-local.
- M7: feasible. Desired/applied pointers and active operation references identify the complete current-authority subset; noncurrent rows require no migration.
- M8: feasible. Existing recreation preserves Agent Workspace storage and already requires exact Provider and Runner evidence before applied promotion.

No requirement or mechanism is blocked. The main implementation risk is coordinated schema/protocol cutover breadth rather than missing technical authority.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-11`
- Status: `approved`
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`, `M8`
- Approved scope: Replace persistent Runtime configuration revisions with bounded current desired/applied state and configuration sequence fencing, then add Owner-authorized Workspace Runtime Profile hard deletion while preserving already running Runtime and Agent Workspace continuity.
