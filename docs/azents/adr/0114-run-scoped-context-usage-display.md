---
title: "ADR-0114: Display Context Usage from the Resolved Run Profile"
created: 2026-07-10
tags: [architecture, chat, frontend, observability]
---

# ADR-0114: Display Context Usage from the Resolved Run Profile

## Context

The chat header currently combines observed token usage with context-window and compaction values derived from the Agent default model. Per-prompt model selection allows a session to execute with a different resolved model, so retaining the Agent default as the denominator would produce a misleading percentage.

A queued input or Composer selection is only target intent. It has not yet been resolved and must not be presented as the model that produced observed usage.

## Decision

Bind the token/context usage indicator to actual AgentRun resolution provenance:

- while a run is active, use that AgentRun's resolved model snapshot and effective context/compaction limits;
- otherwise use the latest successfully resolved terminal run explicitly associated with the displayed token-usage snapshot, regardless of whether its terminal status is completed, failed, stopped, interrupted, or cancelled;
- before any run has resolved successfully, display unknown model, context limit, and usage rather than substituting the Agent default;
- do not change the indicator because of a queued input or current Composer profile.

The displayed token numerator, context-window denominator, model name, and compaction threshold must describe the same resolved run context.

## Rejected options

### Use the current Composer selection

The target may resolve differently, and combining prior observed usage with an unconfirmed future model produces a speculative percentage.

### Continue using the Agent default model

The default is only an initialization target and is not evidence of the model used by the active or latest run.

## Consequences

- Session/chat data must expose active or latest usage-associated resolved run data alongside usage.
- Context usage changes when a new run commits its resolved activation checkpoint, not when the user changes the Composer.
- The indicator remains an observed execution metric rather than a preview.
- Composer target capability and context preview, if desired later, must be presented separately from the observed token usage indicator.
