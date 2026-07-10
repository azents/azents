---
title: "ADR-0112: Display Inference Provenance from User Message Metadata"
created: 2026-07-10
tags: [architecture, chat, frontend, observability]
---

# ADR-0112: Display Inference Provenance from User Message Metadata

## Context

Per-prompt model selection needs durable, discoverable history so users can understand queued inputs, retries, failures, and future dynamic routing. Repeating profile badges on both user and assistant messages would add substantial visual noise. Displaying only the physical resolved model would also replace the stable Agent-owned target label the user actually selected with an implementation detail that can change behind routing policy.

User messages already render compact sent-time metadata. That location directly identifies the prompt whose requested profile created a run boundary without introducing another message row or assistant-response badge.

## Decision

Display the user message's requested model target label beside its existing sent timestamp, using the same compact metadata treatment rather than a badge.

For example:

`12:34 PM · GPT-5.4`

The visible label remains the requested Agent-owned target label throughout queued, running, completed, and failed states. It does not change to the physical resolved model after run start. Reasoning effort and physical routing details are not shown inline by default.

Make the target label metadata interactive and keyboard focusable:

- desktop supports hover and focus;
- touch devices open the same detail surface on tap;
- tapping outside or dismissing the surface closes it.

The detail content includes:

- requested target label;
- requested reasoning effort, including `Default`;
- resolution state while waiting, or failure when target resolution did not complete;
- resolved provider and model snapshot after successful run start;
- effective reasoning effort when it differs in representation from the requested no-override state.

Do not add a separate persistent model label to assistant-message footers. The provenance belongs to the run-triggering user message, and its detail surface carries both requested and resolved information.

## Rejected options

### Show resolved model metadata on every assistant response

This repeats inference metadata throughout the conversation and weakens the connection between the user's per-prompt choice and its run boundary.

### Replace the visible target label with the resolved physical model

Dynamic routing could change the visible history after execution and expose provider details as the primary public policy label.

### Show profile only in the Composer

Users could not inspect which profile was requested by queued, edited, retried, or failed historical messages.

### Render a profile badge separate from sent time

A separate badge adds visual weight even though the existing timestamp metadata row already provides an appropriate prompt-scoped location.

## Consequences

- User-message event data must retain the requested target label and effort.
- Run resolution provenance must be reachable from the user message after successful start.
- Queued messages can show the stable label before any physical model exists.
- The metadata detail component needs hover, focus, and touch interactions with accessible dismissal behavior.
- Dynamic routing stays visible for diagnostics without displacing Agent-owned labels in the normal conversation view.
