---
title: "Agent Runtime Environment Variables Requirements"
created: 2026-10-13
document_role: primary
document_type: requirements
snapshot_id: environment-261013
tags: [runtime, agent, security, frontend]
---

# Agent Runtime Environment Variables Requirements

- Snapshot: `environment-261013`
- Document reference: `environment-261013/REQ`

## Problem

Generic environment variables currently require a configured Toolkit. Agent Runtime settings do not provide a direct per-Agent environment-variable management surface.

## Primary Actor

An authorized Agent manager.

## Primary Scenario

The manager configures environment variables in an Agent's Runtime settings. Subsequent commands executed through that Agent's Runtime Toolkit receive those values without requiring a separate environment-variable Toolkit.

## Supporting Scenarios or Effects

- A manager updates or deletes a variable while retaining unrelated stored values.
- Existing environment-variable Toolkit users continue operating without a migration.

## Goals

- Add per-Agent environment-variable management to Runtime settings.
- Supply configured values through the Runtime Toolkit command-execution path.
- Preserve the existing environment-variable Toolkit unchanged.

## Non-Goals

- Session-scoped, Workspace-shared, or Runtime Profile environment-variable settings.
- Deprecation, removal, or migration of existing environment-variable Toolkits.
- Runner/container-wide configuration or Interactive Terminal injection.
- Changes to Runtime lifecycle, physical provisioning, or configuration history.

## Requirements

### REQ-1. Per-Agent management

Authorized managers can add, update, and delete environment variables from an Agent's Runtime settings.

**Acceptance criteria**

- The Agent settings Runtime page exposes variable names and secret-value editing controls. Session pages and chat Runtime panels do not expose this editor.
- Saved settings belong to exactly one Agent; saving one Agent's settings does not change another Agent's settings.
- Unauthorized users cannot change the settings.

### REQ-2. Runtime Toolkit command injection

The Runtime Toolkit supplies the configured environment variables to commands using the owning Agent's Runtime.

**Acceptance criteria**

- A subsequent Runtime Toolkit command receives the saved value.
- A subsequently executed command no longer receives a deleted value from this setting.
- The setting is available across Sessions using the same Agent Runtime.
- The change does not require a Runtime restart or inject variables into Interactive Terminal.

### REQ-3. Secret protection

Variable values retain the platform's existing encrypted-secret and redacted-management protections.

**Acceptance criteria**

- Values are encrypted at rest.
- Ordinary settings reads return names and value-presence metadata rather than plaintext values.
- Saving unrelated changes does not erase retained secrets.
- Values are not included in Agent prompts, configuration status, events, logs, or validation errors.
- Variable names and sizes are validated before persistence and injection.

### REQ-4. Additive coexistence

Existing environment-variable Toolkits remain available and functional.

**Acceptance criteria**

- No deprecation notice, creation restriction, removal, or data migration is introduced.
- Existing Toolkit settings, credentials, and injection behavior remain unchanged when the new per-Agent settings are empty.
- Coexistence has deterministic handling for duplicate variable names, as established by a separately confirmed material decision.

## Fixed Constraints

- Per-Agent configuration only.
- Injection belongs to the Runtime Toolkit.
- This delivery is additive only.
- Reuse current Agent authorization and encrypted credential protections.

## Open Assumptions

- The owner of the Runtime, rather than a child execution identity, owns the settings when a subagent shares that Runtime.
- Duplicate-name precedence is proposed in the implementation PR for review, rather than treated as a separately confirmed product requirement.

## Confirmation

The requester explicitly confirmed the additive per-Agent Runtime settings scope and Runtime Toolkit injection on 2026-10-13, reviewed the real Storybook UI, and requested a PR. The requester additionally confirmed that the editor belongs to the Agent settings page, not the Session page. This records those confirmed outcomes; it does not claim separate approval of every technical mechanism.
