---
title: "Provider-Native Channel Work Progress Requirements"
created: 2026-07-23
updated: 2026-07-23
tags: [slack, external-channel, activity, agent]
document_role: primary
document_type: requirements
snapshot_id: work-260723
---

# Provider-Native Channel Work Progress Requirements

- Snapshot: `work-260723`
- Document reference: `work-260723/REQ`

## Problem

An external-channel participant currently sees a generic progress title that does not explain what the Agent is doing. Channel Work tasks expose only a title and basic progress state, so provider presentations cannot communicate the task context, completed result, or supporting sources. Implementing those capabilities directly as Slack-shaped state would also make future Discord, GitHub, and other provider integrations depend on Slack's presentation model.

## Primary Actor

A Slack participant observing an Azents Agent work on an authorized thread request.

## Primary Scenario

A participant invokes an Agent in a Slack thread. The initial Tracker immediately shows that the request is being checked. When the Agent begins explicit Channel Work, it supplies a concise current-work title together with the ordered task update. The same Tracker then shows one native Slack Plan whose title describes the work in progress and whose tasks accumulate status, context, results, and relevant sources as the Agent continues. The underlying Channel Work remains provider-neutral so a future integration can render the same meaning with that provider's native presentation. Later updates revise the same work presentation, and the existing final-answer and Tracker-completion lifecycle remains intact.

## Supporting Scenarios

- The Agent changes the Channel Work title when the current phase of work changes.
- A task records explanatory context while it is active and a result after it completes.
- A task identifies relevant URL sources when its progress or result depends on external material.
- Recovery or provider-message replacement restores the latest complete work presentation rather than an earlier title or task revision.
- A future Discord, GitHub, or other external-channel adapter renders the same canonical work state without changing the Agent-facing action contract.

## Goals

- Make provider progress titles communicate the Agent's current work rather than a generic working state.
- Define one provider-neutral Channel Work contract for structured progress, context, results, and sources.
- Use Slack-native Plan and task capabilities for the first provider presentation of that contract.
- Keep provider presentation synchronized with canonical Channel Work across updates and recovery.

## Non-Goals

- Allowing Slack participants to edit or complete Agent tasks from the Tracker.
- Using interactive checkboxes, radio buttons, or other controls that require a Slack interaction callback.
- Changing the explicit Channel Work publication boundary or using ordinary Session Todo as its source of truth.
- Changing the current final-answer delivery, Tracker completion, or provider-mutation retry policy.
- Implementing Discord, GitHub, or another provider's native progress renderer in this snapshot.
- Requiring another provider to imitate Slack's visual layout or wire schema.

## Requirements

### REQ-1. Agent-authored Channel Work title

The Agent's explicit Channel Work action must include a provider-neutral work title alongside its task update, and later work updates may replace that title as the current phase changes.

**Acceptance criteria**

- The Agent receives guidance to write a concise, specific phrase describing what it is currently doing.
- The title follows the participant's language when that language is clear from the conversation.
- The title uses an in-progress form and ends with an ellipsis, such as `Investigating error logs…` or `마케팅 자료 조사하는중…`.
- Generic fixed text such as `Agent is working` is not used after the Agent has supplied a Channel Work title.
- The latest accepted title remains visible until a later Channel Work action replaces it or the current Tracker lifecycle ends.

### REQ-2. Provider-native progress presentation

Once Channel Work contains tasks, each provider presentation must use its native non-interactive progress capabilities when available. Slack must present the work as one native Plan under the Agent-authored current-work title.

**Acceptance criteria**

- One Slack Plan groups the complete ordered task list for the current work cycle.
- Every task has a stable identity and a literal task title.
- Tasks visibly distinguish pending, in-progress, completed, and failed work when those states apply.
- A title or task update mutates the retained Tracker for the current work cycle instead of posting a new progress message.
- The Tracker remains read-only and requires no Slack interaction callback.
- Provider-native rendering does not change the canonical meaning or identity of the work and tasks.

### REQ-3. Task context, results, and sources

The Agent must be able to enrich each provider-neutral Channel Work task with the information needed to understand its progress and outcome.

**Acceptance criteria**

- A task may include details that explain the active work or intended step.
- A task may include output that summarizes the produced result.
- A task may include relevant URL sources with human-readable labels.
- Omitted optional information does not create empty or misleading sections.
- Later updates may add or replace task details, output, sources, and status while preserving task identity and order.

### REQ-4. Immediate checking-to-active-work transition

The provider progress presentation must remain immediately visible before the Agent's first Channel Work action and transition cleanly to the Agent-authored active-work presentation once work is declared.

**Acceptance criteria**

- An eligible invocation still creates its Tracker before Session execution wakes.
- Before the first Channel Work update, the Tracker communicates that the Agent is checking the request.
- The first task-bearing Channel Work action replaces the checking presentation with the current titled Slack Plan on the same Tracker.
- The transition does not create a duplicate progress message.

### REQ-5. Durable current presentation

The latest provider-neutral title and complete task presentation must survive normal continuation, recovery, and provider-message replacement.

**Acceptance criteria**

- Continuation context exposes the current Channel Work title and complete task state to the Agent.
- Recovery renders the latest accepted title, task statuses, details, outputs, and sources.
- Replacement after confirmed external deletion recreates at most one Tracker from the latest desired presentation while work remains active.
- Failed or ambiguous provider mutations do not replace canonical Channel Work state with a partial provider outcome.

### REQ-6. Provider-compatible and accessible output

Each provider presentation must remain valid and understandable across its supported clients and notification or assistive surfaces.

**Acceptance criteria**

- Provider-supported field and length limits are enforced before a provider mutation request, with Slack-specific limits owned by the Slack presentation boundary.
- The Slack Tracker includes meaningful accessible fallback text summarizing the current title and task state.
- Untrusted task text and source labels cannot create unintended mentions, links, or formatting outside their intended Slack fields.
- Only fields supported by the active provider contract are sent to that provider.

### REQ-7. Provider-neutral canonical contract

Channel Work semantics must remain independent from any provider's presentation or wire format.

**Acceptance criteria**

- The Agent-facing action and canonical work state use provider-neutral title, task identity, status, details, output, and source concepts.
- Slack Block Kit objects and Slack-only identifiers are not required inputs to the Agent-facing action or canonical Channel Work state.
- A provider adapter maps canonical work and task state to the provider's supported native presentation.
- When a provider lacks a native equivalent for optional information, its renderer preserves the meaning through a safe fallback or omission without changing canonical state.
- Adding a future provider-native renderer does not require changing existing task identity or the Agent-facing Channel Work action contract.

## Fixed Constraints

- The unprefixed `channel_action` tool remains the only model-facing External Channel publication path.
- Canonical Channel Work and the Agent-facing action remain provider-neutral; provider-specific payloads are created only at the provider presentation boundary.
- Provider mutations retain the existing durable commit-before-call and at-most-once delivery contract.
- The existing one-Tracker-per-work-cycle identity and current final-answer completion policy remain unchanged.
- Provider credentials and tokens must never appear in prompts, UI, logs, progress content, task sources, or delivery records.
- Existing implemented Requirements, ADR, and Design snapshots remain immutable.

## Open Assumptions

- Slack Plan and task capabilities are available to the Agent's Slack app and supported conversation surfaces used by Azents.
- A participant's preferred title language can normally be inferred from the active Slack conversation.

## Confirmation

Confirmed by the requester on 2026-07-23 before ADR and design decisions began.
