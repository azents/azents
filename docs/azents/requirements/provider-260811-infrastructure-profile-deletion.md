---
title: "Provider Infrastructure Profile Deletion Requirements"
created: 2026-08-11
updated: 2026-08-12
implemented: 2026-08-12
tags: [admin, runtime, provider, infrastructure-profile, deletion]
document_role: primary
document_type: requirements
snapshot_id: provider-260811
---

# Provider Infrastructure Profile Deletion Requirements

- Snapshot: `provider-260811`
- Document reference: `provider-260811/REQ`

## Problem

System Administrators cannot permanently remove obsolete Provider-owned Pod or Container Profiles. Keeping an unused Profile indefinitely creates misleading Provider inventory, while deleting one without current impact information could break Workspace Runtime Profile choices or unexpectedly disrupt running Agent Runtimes and their durable Workspace storage.

## Primary Actor

A System Administrator managing a Runtime Provider and its Provider-owned infrastructure Profiles.

## Primary Scenario

A System Administrator selects the always-available delete action for one Pod or Container Profile. Before any destructive confirmation, the Admin surface loads the latest authoritative references and shows whether current Workspace Runtime Profiles still select the target, together with the target's applied-only running Runtime usage. If no current Workspace Runtime Profile references the target, the administrator confirms permanent deletion and only the selected infrastructure Profile is removed. Existing running Runtimes, their retained applied configuration, and Agent Workspace storage continue unchanged.

## Supporting Scenarios

- Current Workspace Runtime Profile references exist, so the administrator reviews the affected Workspaces and Profiles and cannot confirm deletion.
- A running Runtime retains the target only in its applied configuration after current Workspace Runtime Profile authority has moved elsewhere; the administrator sees a warning but may still delete the target.
- References or the target Profile change between preview and confirmation; deletion is rejected without partial effects and the administrator is directed to review current state.
- Reference loading fails; deletion remains unavailable and the administrator can retry without losing page context.

## Goals

- Let System Administrators permanently remove an obsolete Provider-owned Pod or Container Profile.
- Make current blocking references visible before confirmation.
- Preserve existing Runtime execution and Workspace storage when only retained applied configuration uses the target.
- Prevent stale previews and concurrent changes from authorizing an unsafe delete.
- Keep deletion behavior explicit, bounded, and free of fallback or cascade effects.

## Non-Goals

- Deleting or changing the owning Runtime Provider or its advertised capabilities.
- Deleting, rewriting, disabling, or automatically migrating Workspace Runtime Profiles.
- Clearing Agent Runtime Profile selections or selecting replacement Profiles.
- Stopping, restarting, recreating, resetting, or terminally deleting Agent Runtimes.
- Deleting or recreating Agent Workspace storage.
- Preserving a selectable tombstone, compatibility alias, or fallback Profile after deletion.
- Listing individual Agents or individual Runtimes in the reference preview.

## Requirements

### REQ-1. Always-available destructive action

Every Provider-owned Pod or Container Profile has a visible delete action for a System Administrator, regardless of the Profile lifecycle, compatibility, or currently known reference state.

**Acceptance criteria**

- The action remains visible for active, disabled, compatible, and incompatible Profiles.
- Activating the action does not immediately delete the Profile.
- The action first opens a destructive review flow and begins loading current impact information.
- Keyboard users can reach, open, review, cancel, and, when permitted, confirm the flow.

### REQ-2. Fresh current-reference preview

The destructive review flow presents the latest authoritative current Workspace Runtime Profile references to the target before confirmation.

**Acceptance criteria**

- Opening the flow performs a new reference lookup rather than relying only on previously loaded Profile-list data.
- Each blocking reference shows the Workspace name and handle, Workspace Runtime Profile name and ID, number of Agents currently selecting that Workspace Runtime Profile, number of those Agents whose Runtime is currently running, and a control for navigating to the Workspace Runtime Profile detail context.
- Workspace Runtime Profile references are the direct blocking units; Agent and running Runtime counts are impact information within each reference.
- The flow distinguishes loading, loaded-with-no-references, loaded-with-references, and failed states.
- A failed or incomplete lookup never enables deletion.
- Long names, IDs, and reference lists remain readable through bounded wrapping, truncation, or scrolling on desktop and mobile layouts.

### REQ-3. Current references block deletion

A Provider-owned infrastructure Profile cannot be deleted while any current Workspace Runtime Profile references it.

**Acceptance criteria**

- When at least one current reference exists, the flow clearly states that deletion is blocked and does not offer an enabled destructive confirmation.
- No Workspace Runtime Profile, Agent selection, Runtime state, Provider state, or storage is changed by the blocked attempt.
- After references are removed elsewhere, retrying or refreshing the review can produce an unblocked state from current authoritative data.
- Disabled Workspace Runtime Profiles still count as current references while they continue to select the target.

### REQ-4. Applied-only Runtime warning

A currently running Runtime that retains the target only in its applied configuration is reported as non-blocking impact.

**Acceptance criteria**

- The review shows a separate warning count for currently running Runtimes whose retained applied configuration identifies the target but whose current Workspace Runtime Profile authority no longer references it.
- Applied-only usage does not enable or create a current Workspace Runtime Profile reference and does not block deletion.
- The warning explains that deletion will not stop, restart, recreate, reset, or otherwise change those Runtimes or their Workspace storage.
- A zero applied-only count is represented without suggesting hidden impact.

### REQ-5. Explicit and concurrency-safe confirmation

Deletion requires explicit confirmation against the exact Profile version reviewed by the administrator and must remain safe if state changes concurrently.

**Acceptance criteria**

- Confirmation is enabled only after a successful current-reference lookup reports no blocking references.
- The confirmation identifies the exact Profile and states that deletion is permanent.
- The final delete attempt re-evaluates current blocking references rather than trusting the earlier preview alone.
- If the Profile version changed, a current reference appeared, the Profile was already deleted, or authoritative verification cannot complete, the operation makes no partial changes and reports a bounded, distinguishable outcome.
- A stale or newly blocked result prompts the administrator to review current data before another attempt.

### REQ-6. Profile-only permanent deletion

A successful operation permanently removes only the selected Provider-owned infrastructure Profile.

**Acceptance criteria**

- The deleted Profile disappears from Provider Profile inventory and can no longer be selected for new or changed Workspace Runtime Profiles.
- The deleted Profile ID no longer resolves as an active Profile resource.
- The deleted display name may be used by a newly created Profile under the same Provider.
- The owning Provider, its capabilities, and its other infrastructure Profiles remain unchanged.
- The operation does not create a fallback, replacement, alias, or selectable tombstone.

### REQ-7. No cascade and no Runtime disruption

Deleting an unreferenced infrastructure Profile does not cascade into customer configuration or Runtime lifecycle changes.

**Acceptance criteria**

- No Workspace Runtime Profile is deleted, rewritten, disabled, or reassigned.
- No Workspace default or Agent Runtime Profile selection is cleared or changed.
- No Runtime desired or applied configuration is invalidated solely because the infrastructure Profile resource was deleted.
- Existing Provider bindings, running workloads, Runner-reported Workspace paths, and Agent Workspace storage remain intact.
- No automatic Runtime stop, restart, recreation, reset, terminal deletion, or storage cleanup is scheduled.
- Future Runtime creation, start, restart, reset, or recreation continues to require a currently valid Workspace Runtime Profile and existing infrastructure Profile; the deleted Profile is never restored or substituted implicitly.

### REQ-8. Clear operational feedback

The Admin surface gives the administrator a clear result without losing Provider-page context.

**Acceptance criteria**

- Successful deletion closes or completes the review flow, removes the Profile from the visible inventory, and reports success.
- Reference lookup failures, blocked deletion, stale Profile state, concurrent reference creation, and already-absent targets are presented as distinct user-safe outcomes.
- Cancelling the flow makes no change.
- Retrying a failed lookup or stale attempt does not duplicate deletion or trigger Runtime operations.
- User-facing labels, warnings, errors, and confirmation copy are written in English.

## Fixed Constraints

- System Administrator authorization is required for the destructive operation; client visibility is not the authorization boundary.
- Current durable PostgreSQL state is authoritative for blocking references and final deletion eligibility.
- The delete is exact-Provider-scoped and exact-version-fenced.
- The final eligibility check and Profile removal are atomic with respect to concurrently created or changed Workspace Runtime Profile references.
- Current Workspace Runtime Profile references are the only reference category that blocks deletion.
- Retained applied configuration is evidence, not a foreign-key lifecycle authority over the mutable Profile resource.
- The flow must preserve the existing Runtime Provider detail information architecture and remain usable on desktop and mobile.
- Existing implemented Requirements, ADRs, Designs, and Living Specs remain unchanged until an approved design is implemented and verified.

## Open Assumptions

- The Workspace Runtime Profile detail navigation destination may require a new Admin-readable detail context because the current Admin application does not expose that destination.
- Exact presentation of the applied-only warning and reference-list pagination or bounding will be defined in the ADR and Design without changing the required information or blocking semantics.

## Confirmation

Confirmed by the requester on 2026-08-11 before ADR and design decisions began.
