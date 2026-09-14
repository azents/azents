---
title: "Transient Model Fallback Status Requirements"
created: 2026-09-13
updated: 2026-09-13
tags: [model, fallback, frontend]
document_role: primary
document_type: requirements
snapshot_id: model-260913
---

# Transient Model Fallback Status Requirements

- Snapshot: `model-260913`
- Document reference: `model-260913/REQ`

## Problem

The model picker currently exposes persistent availability, cooldown, and recovery controls even when no fallback is running. This exceeds the intended product behavior and makes an internal routing condition look like a standing user-management surface.

## Primary Context

### Primary Actor

A user chatting with an Agent whose selected semantic model label has ordered fallback candidates.

### Primary Scenario

When the active Run moves from its Primary candidate to a fallback candidate, the composer briefly indicates that fallback is in use. Outside that active fallback interval, the model picker remains the ordinary model and reasoning selector with no availability section or recovery controls.

## Supporting Scenarios or Effects

- Automatic quota fallback continues without requiring user action.
- A reload or live-state resync shows the same transient status while the fallback Run remains active.

## Goals

- Show fallback status only while the current active Run is using a fallback candidate.
- Remove the persistent Model availability section and its cooldown and recovery actions from the model picker.

## Non-Goals

- Changing ordered candidate configuration or automatic fallback routing.
- Changing Workspace cooldown, probe, or internal recovery behavior.
- Adding fallback metadata to normal assistant responses.

## Requirements

### REQ-1. Active fallback status only

The composer shows a compact fallback status only while the current active Run is using a fallback candidate.

**Acceptance criteria**

- A Primary-candidate Run shows no fallback status.
- After a quota transition selects a fallback candidate, the active composer shows a non-color-only `Fallback` status.
- The status disappears when the active Run ends or live state no longer reports fallback use.
- Reload and live resync reproduce the status only for the still-active fallback Run.

### REQ-2. Ordinary model picker outside fallback

The model picker contains only the ordinary model, reasoning-effort, execution-option, and existing context controls outside an active fallback Run.

**Acceptance criteria**

- The picker has no `Model availability` heading or panel.
- The picker has no cooldown countdown, current-fallback detail, refresh action, `Primary retry`, `Primary next`, or cancellation action.
- Opening the picker does not start a model-availability query.

### REQ-3. Preserve automatic fallback behavior

Removing the persistent picker controls does not change automatic candidate selection or quota fallback execution.

**Acceptance criteria**

- A quota or billing failure still advances to the next compatible candidate.
- The successful fallback candidate still supplies the active Run's model display and completes the logical operation normally.

## Fixed Constraints

- The transient status is derived from authoritative active Run state, not from a separate standing availability poll.
- Normal assistant messages remain free of fallback badges or routing metadata.

## Open Assumptions

- Existing public availability and reservation backend contracts are outside this UI correction unless separately requested.

## Confirmation

Confirmed by the requester on 2026-09-13 before corrective implementation began.
