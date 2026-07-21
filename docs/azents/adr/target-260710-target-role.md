---
title: "Keep Agent Main Model as the Default Target"
created: 2026-07-10
tags: [architecture, agent, frontend, workspace, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: target-260710
historical_reconstruction: true
migration_source: "docs/azents/adr/0109-agent-default-model-target-role.md"
---

# target-260710/ADR: Keep Agent Main Model as the Default Target

## Context

Per-prompt model selection moves the active human choice into the composer, but a new AgentSession has no last-used profile until its first run starts. System execution can also begin before a human has selected a profile. Removing the Agent main model setting would therefore require a separate mandatory-selection or system fallback mechanism.

The existing `main_model_label` and Workspace `default_main_model_label` already define deterministic Agent-owned targets. Their product meaning can narrow from the model used for every run to the initial default used before session-specific selection exists.

## Decision

Keep `Agent.main_model_label` and its denormalized effective `model_selection`, but define the label as the Agent's default model target.

The Agent default target initializes the composer for a new session and supplies the initial run profile only while the AgentSession has no explicit input profile and no persisted last-used profile. After the session records a last-used profile under [used-260710/ADR](./used-260710-used-inference-profile.md), that session profile takes precedence.

Keep `WorkspaceModelSettings.default_main_model_label` as the default copied into newly created Agents. Workspace settings do not control active session choices after Agent creation.

Keep `lightweight_model_label` and its Workspace default as the compaction/lightweight model setting. Per-prompt main model selection does not move lightweight model selection into the composer.

Treat the Agent-level configured reasoning effort as the initial default effort when the default target currently supports that effort. Per-prompt choices and AgentSession last-used effort take precedence.

Use user-facing terminology that reflects these roles:

- Agent settings: `Default model` and `Lightweight model`;
- Workspace settings: defaults for new Agents;
- prompt composer: `Model` and conditional reasoning effort controls.

## Rejected options

### Remove the Agent main model setting

This leaves new sessions and initial non-user-triggered execution without a deterministic target and requires a separate fallback policy.

### Continue presenting it as the model for every run

That wording becomes inaccurate once each prompt and AgentSession can choose a different profile.

### Move lightweight model selection into the composer

Lightweight selection controls compaction infrastructure rather than the user's current inference target and should remain an Agent setting.

## Consequences

- Existing database columns remain and change product semantics rather than being removed.
- Agent and Workspace settings copy and denormalized snapshot invariants remain useful.
- Frontend settings copy must distinguish default main selection from the active session profile.
- Internal non-user-triggered execution that has no explicit profile retains deterministic behavior through session/default precedence; run-producing public chat requests submit a profile under [public-260710/ADR](./public-260710-public-inference-profile-request-contract.md).
- Context-window UI can no longer treat the Agent default main snapshot as the active run model once a session profile exists.

## Migration provenance

- Historical source filename: `0109-agent-default-model-target-role.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
