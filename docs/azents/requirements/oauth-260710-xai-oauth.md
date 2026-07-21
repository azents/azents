---
title: "xAI Grok OAuth Provider Historical Requirements Reconstruction"
created: 2026-07-10
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: oauth-260710
historical_reconstruction: true
migration_source: "docs/azents/design/xai-oauth-provider.md"
---

# xAI Grok OAuth Provider Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `oauth-260710`
- Source: `docs/azents/design/oauth-260710-xai-oauth.md`
- Historical source date basis: `2026-07-10`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents users want to connect Grok with their own xAI account subscription instead of only using an xAI platform API key. xAI has publicly documented and announced user-authorized Grok OAuth flows in open-source agents such as Hermes and OpenCode. The subscription OAuth path is operationally different from an API key path: quota and entitlement are owned by the user's xAI account, tokens must be refreshed, and xAI may reject inference with HTTP 403 when the account is not entitled to the OAuth API surface.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Add an experimental xAI Grok OAuth LLM provider that connects with OAuth device authorization.
- Keep the provider separate from the future xAI API key provider.
- Store access and refresh tokens only in encrypted provider integration credentials.
- Reuse the existing Responses/LiteLLM runtime path for Grok model calls.
- Classify xAI OAuth HTTP 403 as an entitlement or allowlist failure, not as a stale-token failure.
- Gate the provider behind an operational feature flag and xAI OAuth client id configuration.

## Non-goals

- Add xAI API key provider support in this phase.
- Claim or imply an official Azents-xAI partnership.
- Reuse or hard-code another application's OAuth client identity.
- Add xAI image, video, TTS, transcription, or X search surfaces in this phase.
- Generalize all LLM OAuth providers into a shared storage abstraction in this phase.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
