---
title: "Runtime Browser Selection Decisions"
created: 2026-10-23
tags: [browser, runtime, architecture]
document_role: primary
document_type: adr
snapshot_id: browser-261023
---

# Runtime Browser Selection Decisions

- Snapshot: `browser-261023`
- Requirements: [browser-261023/REQ](../requirements/browser-261023-runtime-engine-selection.md)
- Mode: Collaborative
- Decision owner: Requester

## Decision Map

- Accepted: browser-only restart and a distribution containing both supported implementations (D1).
- Fixed by Requirements: per-Agent explicit selection, unchanged Patchright default, experimental Camoufox, common tool and security contract, separated native state, no silent fallback.
- Accepted: explicit confirmation followed by immediate browser-only application when saving the selection (D2).
- Accepted: Camoufox registers viewer popup tabs without automatic tab selection, while Patchright and explicit Agent expectations retain their behavior (D3).
- Design synthesis: browser-specific requested/applied coordination must retain unrelated Runtime authority and use existing request/operation and current Runner identities. The proposed complete Design revision 1 records its exact mechanisms for approval; no independent version counter or Provider recreation mode is authorized.
- Feasibility: the verified public-SDK popup limitation is addressed by D3. Full product operation/viewer parity, packaged browser/library security and compatibility, image startup/reporting and exact switch fencing remain implementation acceptance gates.
- Agent-owned details: equivalent internal module/class layout, fixture composition, and local implementation identifiers.

## D1. Switch only the browser subsystem in the initial distribution

- Reference: `browser-261023/ADR-D1`
- Accepted: 2026-10-23
- Authority: Requester choice after the browser-only restart versus full Runtime recreation briefing.
- Requirements: `browser-261023/REQ-1`, `browser-261023/REQ-3`, `browser-261023/REQ-4`, `browser-261023/REQ-5`.

### Decision

Include both supported browser implementations in the current Runtime distribution and apply an engine change by restarting the browser subsystem, retaining the Runtime and unrelated execution capabilities. Do not introduce browser-specific Runtime images or a recreation mode in this snapshot.

### Alternatives

1. Browser-only restart with both implementations available: selected. Preserves the Runtime, shell processes and unrelated work, but requires an explicit browser transition and increases the distribution size.
2. Browser-specific distribution selected through full Runtime recreation: deferred. May become appropriate as implementation count and distribution size increase, but would disrupt unrelated Runtime work and require a different lifecycle boundary.

### Consequences and risks

- Old browser pages, active browser effects, viewer attachments and stale browser input authority must be retired at the browser transition boundary.
- This decision does not claim that old tabs survive switching or that authentication transfers between browser families.
- Keeping shell/process execution does not authorize leaving old browser automation effects running into the new implementation.
- The current Runner capability and browser authority model must be investigated for browser-only reconfiguration; a Runtime generation change is not a shortcut to browser invalidation.
- Two browser binaries and libraries increase image and maintenance cost now. Future image specialization requires a separate requirement and decision snapshot, not an automatic threshold-driven mode.
- Switching time, failure handling and application trigger were left open by D1; D2 below subsequently selects the application trigger. Neither decision authorizes speculative fallback or automatic rollback.

## D2. Confirm and immediately apply a changed selection

- Reference: `browser-261023/ADR-D2`
- Accepted: 2026-10-23
- Authority: Requester approval of option A, followed by the request to proceed through implementation and PR creation.
- Requirements: `browser-261023/REQ-1`, `browser-261023/REQ-2`, `browser-261023/REQ-4`.

### Decision

Saving a changed browser selection requires confirmation that the Agent's open browser tabs and in-progress browser operations will end. After confirmation, immediately initiate the browser-only switch rather than defer it until an unrelated future Agent/browser command. Keep shells and unrelated Runtime jobs running.

### Alternatives

1. Confirm and immediately apply on save: selected. Gives the user a direct, intentional transition and visible result.
2. Save a pending choice until a separate future browser restart: rejected for the initial behavior. Retains open tabs immediately but leaves requested and applied engines different until a later action.

### Consequences and risks

- The confirmation applies to browser resources across this Agent's Sessions, not only the currently visible tab.
- The operation must distinguish requested, applying, applied and failed states; a dispatched message is not evidence of successful browser application.
- Admission and viewer inputs for retired browser identities must fail closed during and after switching. Side effects already processed by external sites are not undone or replayed.
- Runtime-free or offline Agents cannot be made running implicitly by this setting. Requested selection can be retained for the next valid Runtime start, with no claim that an offline browser switched.
- Failure leaves browser availability explicit; it does not silently return to the previous engine or stop unrelated Runtime work.
- This acceptance fixes user-visible timing but does not approve a second configuration authority, a new versioning scheme, or a specific unreviewed transport mechanism.

## D3. Keep Camoufox viewer popup selection explicit

- Reference: `browser-261023/ADR-D3`
- Accepted: 2026-10-23
- Authority: Requester approval of the specific Camoufox manual popup-tab selection exception after the delayed-popup feasibility briefing.
- Requirements: `browser-261023/REQ-3`.

### Decision

Register popup pages in the existing task/page projection for both implementations. Camoufox does not emit the viewer's automatic popup-selection hint; users select its new tabs explicitly. Retain the existing Chromium exact-owner tracker for Patchright and pre-armed explicit Agent popup expectations for both implementations.

### Alternatives

1. Explicit viewer selection for Camoufox: selected. Preserves popup access without inventing an unverified native creation identity.
2. Match a later popup event to the active attachment or URL: rejected. Delayed responses can arrive after the original pointer interaction ends, and URLs do not identify an exact native page or its initiating input.
3. Require identical automatic selection before supporting Camoufox: not selected for this snapshot. It requires additional native Firefox integration beyond the currently verified public SDK behavior.

### Evidence and consequences

- A local response-gated fixture reproduced that both public SDK page/popup events arrive after the initial response starts; the original live pointer owner has already ended.
- Camoufox's earlier context request event did not expose the exact page frame for the initial navigation, so it cannot safely substitute for Chromium target creation metadata.
- Popup registration, source fencing, stale-input rejection, permission checks and explicit Agent expectations are unchanged requirements. This exception does not authorize private SDK introspection, page-script interception, guessed attribution or weakened browser authority.
- The experimental Camoufox presentation must disclose the manual popup tab-selection behavior without suggesting that popup creation itself is unsupported.
