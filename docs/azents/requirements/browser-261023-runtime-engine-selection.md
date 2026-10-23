---
title: "Runtime Browser Selection Requirements"
created: 2026-10-23
implemented: 2026-10-24
tags: [browser, runtime, configuration]
document_role: primary
document_type: requirements
snapshot_id: browser-261023
---

# Runtime Browser Selection Requirements

- Snapshot: `browser-261023`
- Document reference: `browser-261023/REQ`

## Problem

Session Browser currently has one browser implementation. Users who want to try an alternative browser must not require a global replacement of the default browser or different Agent tools.

## Primary Context

### Primary Actor

An authorized Agent administrator configuring that Agent's Runtime.

### Primary Scenario

The administrator selects the browser implementation in the Agent's Runtime settings, understands any experimental warning and application impact, applies the change, and uses the selected implementation through the existing Session Browser tools and panel.

## Supporting Scenarios or Effects

- Existing Agents continue using the current default without an unsolicited browser change.
- An administrator can return to the default browser after trying the alternative.
- Users can distinguish the requested browser from the browser actually in use when a change is pending or fails.

## Goals

- Make Camoufox an explicit opt-in browser choice while retaining Patchright as the default.
- Preserve the common Session Browser behavior and security contract across supported implementations.
- Make switching effects and failures predictable and visible.

## Non-Goals

- Guaranteed site access, CAPTCHA clearance, or undetectability.
- Arbitrary user-provided browser executables, plugins, remote debugging endpoints, or local personal browser attachment.
- Per-action, per-tab, per-site, or Agent-selected automatic engine switching.
- Automatic authentication transfer between browser implementations.
- A global default replacement, deployment, or automatic PR merge.

## Requirements

### REQ-1. Explicit per-Agent Runtime browser choice

An authorized administrator can choose Patchright or Camoufox through the Agent's Runtime settings.

**Acceptance criteria**

- Browser selection is visible and editable within existing Runtime administration permissions.
- The selection applies to the Agent's Runtime rather than changing other Agents or the Workspace-wide default.
- Existing and newly created Agents use Patchright unless Camoufox is explicitly selected.
- Browser enablement remains independent: selecting a browser does not enable a disabled Session Browser or allocate a Runtime implicitly.

### REQ-2. Experimental alternative disclosure

Camoufox is clearly presented as an experimental alternative.

**Acceptance criteria**

- The choice discloses experimental stability and that site acceptance is not guaranteed.
- Users can identify both the requested selection and the currently applied selection while they differ.
- A request to return to Patchright is supported through the same settings flow.

### REQ-3. Preserve the browser operation contract

Users and Agents use the existing browser tools and panel regardless of the selected implementation.

**Acceptance criteria**

- Supported implementations provide open/observe/action, native input and direct touch, page/frame handling, popups, dialogs, uploads/downloads, captures, and live preview under the same observable contract.
- Camoufox registers manually opened popup tabs but does not automatically select them in the viewer; users select those tabs explicitly. Patchright retains its existing exact-owner automatic selection, and explicit Agent popup expectations remain supported for both implementations.
- Existing source fencing, current-resource identity, stale-input rejection, cancellation, and uncertain-result non-replay behavior remain authoritative.
- Unsupported or failed required behavior is reported as a failure rather than presented as success.
- Contract verification covers both implementations and does not depend on third-party challenge success.

### REQ-4. Explicit change application and failure behavior

The browser change has a visible application boundary and never silently switches an active browser's engine.

**Acceptance criteria**

- Changing the browser restarts only the browser subsystem; the Runtime instance, shells, and unrelated running work are retained.
- The user confirms that the Agent's open browser tabs and browser operations will end when saving a changed selection; the browser-only switch then starts immediately.
- Saving the setting does not implicitly start a stopped Runtime or allocate a missing Runtime. Such a selection is retained for the next valid start and is not presented as applied prematurely.
- Existing pages are not claimed to survive an engine switch; old page and input authority is retired before replacement input is admitted.
- A failed or unavailable selected browser is reported explicitly and does not silently fall back to another implementation.
- Browser initialization failure does not disable unrelated Runtime capabilities.

### REQ-5. Preserve isolated native state

Native site state remains isolated by Session and browser implementation.

**Acceptance criteria**

- One Session cannot read another Session's browser state.
- Switching engines does not copy cookies, credentials, or application storage between browser families.
- Returning to an implementation retains its own previously saved state where the existing durable Runtime lifecycle preserves that data.
- Existing default-browser state remains usable without deleting it as a migration shortcut.

## Fixed Constraints

- Retain existing authorization, Runtime network restrictions, confidential-input handling, and supported Runtime lifecycle boundaries.
- Do not add engine-specific Agent tools or relax the common browser security contract to accommodate Camoufox.
- Keep the existing default implementation supported.
- Do not introduce a new configuration versioning scheme as part of browser selection.

## Open Assumptions and Decisions

- The requester selected browser-only restart on 2026-10-23. Full Runtime recreation solely for a browser selection change is excluded from this snapshot.
- Both browser choices must be available in the current Runtime distribution. Per-browser image specialization for future image growth is deferred, not a second mode introduced by this snapshot.
- Failure/recovery mechanisms and browser configuration propagation require subsequent material design decisions.
- The available Camoufox release and Python/browser pairing must pass compatibility and supply-chain checks; research results from an earlier prerelease are not production acceptance evidence.

## Confirmation

The requester accepted the proposed optional browser-selection scope on 2026-10-23 and chose browser-only restart for the initial implementation. The default remains Patchright; Camoufox is opt-in in the Agent's Runtime settings. The requester explicitly deferred per-browser image specialization and full Runtime recreation until future distribution growth warrants reconsideration. No authority for that future mode is created by this snapshot.

On 2026-10-23 the requester accepted the specific Camoufox viewer difference in REQ-3: popup registration without automatic viewer tab selection, preserving Patchright behavior and explicit Agent popup expectations.
