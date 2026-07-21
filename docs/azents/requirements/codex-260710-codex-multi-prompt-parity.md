---
title: "Codex Multi-Agent V2 Subagent Prompt Parity Historical Requirements Reconstruction"
created: 2026-07-10
implemented: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: codex-260710
historical_reconstruction: true
migration_source: "docs/azents/design/codex-multi-agent-v2-prompt-parity.md"
---

# Codex Multi-Agent V2 Subagent Prompt Parity Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `codex-260710`
- Source: `docs/azents/design/codex-260710-codex-multi-prompt-parity.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents currently emits one generic subagent collaboration prompt for both the root agent and spawned children. The prompt mixes Azents-specific lifecycle guidance with collaboration policy, omits the Codex root/child distinction, and does not include the Codex shared-workspace or explicit-request-only guidance.

The requested change is prompt parity only. It must not redesign or replace the existing subagent runtime, mailbox, broker, input-buffer, terminal-result, or `wait_agent` implementation.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Use the active Codex Multi-Agent V2 prompt text as the source of truth and make the Azents subagent collaboration prompt match it, leaving only wording required by actual Azents names and tool availability.

The implementation must fit in one focused PR.

## Non-goals

- Collaboration tool names, parameter names, schemas, descriptions, validation messages, or return values.
- `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`, or `interrupt_agent` behavior.
- Mailbox, broker, input-buffer, terminal-result, observation-cursor, run-finalization, or worker changes.
- System-prompt architecture, provider request roles, a new developer-prompt pipeline, or context-inspector UI/API changes.
- Database migrations, public API changes, generated clients, feature flags, compatibility layers, ADRs, or stacked PRs.
- Living-spec changes outside the existing Subagent Toolkit prompt paragraph.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
