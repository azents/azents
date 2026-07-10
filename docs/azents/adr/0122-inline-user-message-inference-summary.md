---
title: "ADR-0122: Project Compact Inference Summaries with User Messages"
created: 2026-07-10
tags: [architecture, api, chat, frontend, observability]
---

# ADR-0122: Project Compact Inference Summaries with User Messages

## Context

ADR-0112 makes the requested target label beside user-message sent time interactive. Its detail surface needs requested effort, latest run resolution, and safe failure information. Fetching that data only after hover or tap would introduce visible loading, per-message requests, and client cache coordination. Returning complete internal AgentRun snapshots would expose irrelevant integration/catalog diagnostics and unnecessarily enlarge history payloads.

A user message can be associated with several runs through manual retry, but the compact chat interaction needs the latest attempt by default rather than full audit history.

## Decision

Include a compact safe inference projection with each user message in normal chat history and live projections.

The projection contains:

- the message's `requested_inference_profile` with target label and nullable requested effort;
- nullable `inference_run_summary` for the latest associated AgentRun;
- run ID and status;
- a nullable resolved-profile summary containing safe provider name, physical model identifier, display name, and effective reasoning effort;
- nullable typed failure code and localized/user-safe message when resolution failed.

While an input is queued and has no associated run, return requested profile with a null run summary. When a run is created, resolved, or fails, update the live projection so the hover/focus/touch detail is immediately available without another request.

Never include credentials, decrypted provider configuration, the provider integration ID, full normalized catalog snapshot, source diagnostics, or other internal `AgentModelSelection` fields in this chat projection.

If manual retry associates several AgentRuns with one user message, select the latest run by session run index for the inline summary. Full attempt history remains available through existing failed-run/run-detail flows and is not duplicated into every chat event.

## Rejected options

### Fetch provenance only when the user opens details

This adds interaction latency and creates an N-request cache problem for a frequently available lightweight detail.

### Embed the full AgentRun model-selection snapshot

The full snapshot is larger than the UI needs and contains internal integration/catalog diagnostics that are not part of the public chat contract.

### Return only requested profile

The detail interaction could not explain actual dynamic/static resolution or typed failure state.

## Consequences

- Chat history, partial history, pending live-event, and run-update projections need a common compact inference-summary response type.
- Live state must invalidate or update the associated user-message projection when run provenance changes.
- Frontend hover/focus/touch UI opens immediately from existing state.
- Public API serialization explicitly allowlists safe resolved fields rather than dumping the stored JSON snapshot.
- Normal chat payload grows modestly per user message but avoids additional per-interaction network requests.
