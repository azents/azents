---
title: "ADR-0113: Restore the Latest Composer Profile Intent on Reload"
created: 2026-07-10
tags: [architecture, chat, frontend, session]
---

# ADR-0113: Restore the Latest Composer Profile Intent on Reload

## Context

AgentSession last-used profile fields update only after successful run-start resolution. A user can select and submit a different profile while that input remains queued, or select another profile in an unsent local Composer draft. Reloading from only the last successfully resolved session profile would revert the Composer to an older selection and misrepresent the user's latest intent.

Updating the AgentSession fields at enqueue time would preserve the UI selection but corrupt their meaning when resolution later fails. Local drafts also need to retain the profile selected for their unsent prompt independently of server state.

## Decision

Initialize or restore the normal Composer profile using this precedence:

1. the browser-local unsent Composer draft profile;
2. the most recent durable run-producing human input with a non-null requested profile, considering a pending InputBuffer or its promoted user-message event by acceptance/submission order;
3. the AgentSession last-used successfully resolved profile;
4. the Agent default profile.

Persist message text, selected action, requested target label, and requested reasoning effort together as one local Composer draft. A profile-only change is meaningful unsent intent and is persisted even when message text and action are empty.

The latest qualifying submitted user-message profile preserves cross-reload and cross-client intent while an input is queued or while its run has not successfully activated. Commands with no inference profile are skipped. A manual retry does not become newer Composer intent because it does not create a new human user message; an edited replacement message does. This precedence does not update the semantic AgentSession last-used fields. Failed target resolution likewise leaves the prior activated session profile unchanged, while the failed user message continues to expose its requested profile for history and explicit correction.

Editing a historical message temporarily initializes the editor from that message's requested profile under ADR-0107. Cancelling edit restores the normal Composer state determined by its current draft/latest-intent state rather than replacing it with the edited message profile.

## Rejected options

### Restore only AgentSession last-used profile

This loses a newer queued or unsent selection after reload and makes the Composer visibly move backward.

### Update AgentSession last-used profile on enqueue

A target that later fails resolution would overwrite the last known successful profile and affect implicit execution incorrectly.

### Persist only draft text and action

The prompt's Model and effort are part of the same user intent and must survive reload with its content.

## Consequences

- Composer draft serialization adds target label and effort.
- Profile-only drafts need an explicit persisted representation rather than being cleared as empty text.
- Session bootstrap data must expose or make it possible to derive the latest submitted user-message requested profile.
- AgentSession fields retain their successful-run semantics and remain suitable for non-user-triggered execution.
- Cross-device Composer initialization can follow the latest submitted intent even though a purely local unsent draft remains device-specific.
