---
title: "Toolkit Wake-Up Snapshot Revision"
created: 2026-07-21
tags: [toolkit, runtime, session, architecture, security]
document_role: primary
document_type: adr
snapshot_id: toolkit-260721
---

# Toolkit Wake-Up Snapshot Revision

- Snapshot: [toolkit-260721/REQ](../requirements/toolkit-260721-wakeup-snapshot-revision.md)
- Document reference: `toolkit-260721/ADR`

## Context

Toolkit resolution already reads current source data for actionable Runs, but the
session lifecycle reuses instances by stable identity alone. This causes a
newly-resolved Toolkit state to be discarded when its session key matches an
existing instance.

## Decisions

### ADR-D1. Use an explicit ToolkitConfig revision as the persisted source version

Affected requirements: [toolkit-260721/REQ-1](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-1-revisioned-toolkit-source) and [toolkit-260721/REQ-4](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-4-credential-confidentiality).

ToolkitConfig receives a non-null integer `revision` that starts at `1` and
increments with every persisted ToolkitConfig update, including encrypted
credential changes. Snapshot comparison uses the ToolkitConfig ID and revision,
not timestamps, plaintext credentials, or credential hashes.

### ADR-D2. Resolve source state on each actionable wake-up and reuse only equal revisions

Affected requirements: [toolkit-260721/REQ-2](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-2-wake-up-snapshot-reconciliation) and [toolkit-260721/REQ-3](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-3-atomic-replacement).

Every actionable SessionWakeUp resolves its current Toolkit binding snapshot.
The session lifecycle compares each binding's stable identity and source
revision. Equal bindings reuse their entered instance; changed bindings enter a
new instance and replace the old one only after the full requested snapshot
enters successfully.

Attach, detach, enable, disable, slug, and Toolkit type changes alter the
binding set or revision and therefore reconcile on the next actionable wake-up.

### ADR-D3. Keep provider-owned token refresh outside persisted snapshot revision

Affected requirements: [toolkit-260721/REQ-1](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-1-revisioned-toolkit-source) and [toolkit-260721/REQ-4](../requirements/toolkit-260721-wakeup-snapshot-revision.md#req-4-credential-confidentiality).

Persisted ToolkitConfig revisions represent manager-controlled Toolkit source
changes. Providers retain responsibility for ephemeral external token renewal
that does not change ToolkitConfig. This avoids writing or comparing secrets for
ordinary token expiry handling.

## Consequences

- Manager-controlled Toolkit changes apply to the next actionable wake-up without
  restarting the worker or session.
- Unchanged MCP and other stateful Toolkit instances preserve their connection and
  background state.
- Toolkit source updates gain an additional schema migration and repository write
  responsibility.
