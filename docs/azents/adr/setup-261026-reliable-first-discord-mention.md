---
title: "Reliable First Discord Mention Decisions"
created: 2026-10-26
tags: [external-channel, discord, reliability]
document_role: primary
document_type: adr
snapshot_id: setup-261026
---

# setup-261026/ADR: Reliable First Discord Mention

Authority: [setup-261026/REQ](../requirements/setup-261026-reliable-first-discord-mention.md).
Mode: Collaborative. Decision owner: Requester.

## Fixed Outcomes

- Preserve existing setup, selection, access and provider-control ambiguity policy.
- No Session or Agent execution before current setup and access requirements succeed.
- Use PostgreSQL-owned domain state and the existing producer-local Job Runtime.
- Ordinary transport reconnect is not a revocation of already committed setup receipt; configuration change and actual disconnection remain authoritative.

## setup-261026/ADR-D1 — Extend the existing setup claim

Accepted by the requester on 2026-10-26 after comparing claim extension with a separate receipt table.

The channel-scoped setup claim owns its bounded latest source and preparation execution state. Add preparation status, configuration snapshot, attempt scheduling and owner/expiry fields to that claim. Reuse existing claim/source revisions to fence replacement and selection. Preparation jobs carry only the claim identity; they do not persist a second copy of canonical message content or a second setup lifecycle.

Rejected: an independent generic inbound receipt queue requiring reconciliation with setup claim replacement, expiry and selection. Rejected: process-local tasks as the durability authority. Existing configured conversation ingress remains unchanged.

Impacts: REQ-1 through REQ-4. Existing rows have no active preparation and retain their current behavior. New work stops after setup/access/selection control preparation rather than creating a conversation directly.

## Derived Failure Boundary

Provider mutations retain the existing no-blind-replay policy for uncertain outcomes. Preparation is recoverable before dispatch. A committed dispatch intent whose execution ownership expires is classified as uncertain and emits a sanitized diagnostic rather than blindly sending a second control. This deliberately prefers an explicit uncertain terminal outcome to a false exactly-once guarantee. Definite failures before mutation can retry within bounded limits. This is derived from REQ-4 and the existing provider-effect boundary, not a new external-delivery guarantee.
