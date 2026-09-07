---
title: "Discord Conversation Settings Select Controls Decisions"
created: 2026-09-07
tags: [discord, external-channel, settings, architecture]
document_role: primary
document_type: adr
snapshot_id: settings-260907
---

# settings-260907/ADR: Discord Conversation Settings Select Controls

- Snapshot: `settings-260907`
- Document reference: `settings-260907/ADR`
- Requirements:
  [`settings-260907/REQ`](../requirements/settings-260907-discord-select-controls.md)
- Mode: Collaborative
- Decision owner: Requester

## Context

Connected Discord Conversation settings currently render one button per location or response-mode value. Parent settings therefore use four equal-weight buttons across two rows, while thread settings use two buttons. Every supported entry point delegates to the same settings response service, but the settings surface has no Session navigation control.

Discord String Select components represent one-of-many values directly and return one selected value in the authenticated component interaction. Existing Discord interaction decoding already accepts one bounded selected value, while signed settings component IDs retain canonical setting or Binding identity and generation fences.

The confirmed Requirements replace connected-settings choice buttons with compact selections, retain the surface after immediate mutations, add exact Session navigation when available, and preserve first-time setup buttons and all existing authorization boundaries.

## Decisions

### settings-260907/ADR-D1. Represent each setting axis with its own String Select

Parent settings use separate location and response-mode Selects. Thread settings use only the response-mode Select. Every Discord settings entry point uses this shared presentation.

A combined Select is rejected because location and response mode are independent values. A modal is rejected because it adds an opening and submission step to settings that can apply immediately.

### settings-260907/ADR-D2. Apply one selection immediately and re-render canonical settings

Each Select interaction commits the existing single-axis mutation, then updates the original ephemeral response with the complete settings surface reconstructed from committed state. The selected option provides the success feedback, keeps the other setting available, and removes the need for a separate Save action or terminal confirmation screen.

The prior one-shot success confirmation is replaced for connected settings. First-time setup retains its existing confirmation because setup continues the deferred original mention rather than editing an established settings surface.

### settings-260907/ADR-D3. Keep authority in the signed scope and authenticate the selected value at ingress

The component custom ID signs the operation category, origin interaction, canonical setting or Binding identity, and current generation fence. The selected value remains a closed provider payload value authenticated by Discord's signed interaction request and is validated against the operation category before mutation.

Encoding every possible value into a separate signed component ID is rejected because it would preserve button-shaped action semantics instead of representing one setting with one selection control.

### settings-260907/ADR-D4. Show Session navigation only for one exact connected Binding

The settings renderer derives View session from the current canonical Workspace, Agent, and Binding-owned Session. Thread settings always have this exact Binding. Parent settings show it only when the parent channel currently has a connected Binding; a parent configured for threads or not yet connected does not invent or choose among Sessions.

Persisting a Session URL in provider controls is rejected because Binding, Agent, Workspace, and Web route authority already exist canonically and may change before presentation.

### settings-260907/ADR-D5. Preserve first-time setup buttons

The pre-Session setup choice remains `Answer in this channel` and `Answer in threads` buttons. Setup is a one-time continuation decision with distinct deferred execution behavior, not an editable connected-settings surface.

## Consequences

- Parent settings become two labeled single-selection rows plus an optional Session link row.
- Thread settings become one labeled single-selection row plus a Session link row.
- A participant can change both parent settings without rerunning the command.
- Tracker, joined-presence, slash-command, and message-command entry points remain visually and behaviorally consistent because they share one renderer.
- Current stale-control, authorization, mutation, cleanup, and first-time setup behavior remains authoritative.
- No database, public API, generated client, configuration, or provider credential change is required.
