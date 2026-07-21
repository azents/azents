---
title: "Model-Specific Image Generation Execution Historical Decision Reconstruction"
created: 2026-07-18
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: image-260718
historical_reconstruction: true
migration_source: "docs/azents/design/model-specific-image-generation.md"
---

# Model-Specific Image Generation Execution Historical Decision Reconstruction

- Snapshot: `image-260718`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/model-specific-image-generation.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### image-260718/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: External API contract

The client executor calls:

```text
POST https://api.x.ai/v1/images/generations
Authorization: Bearer <selected xAI integration credential>
Content-Type: application/json
```

The request uses the documented public image model by default:

```json
{
  "model": "grok-imagine-image",
  "prompt": "...",
  "n": 1,
  "aspect_ratio": "auto",
  "resolution": "1k",
  "response_format": "b64_json"
}
```

The model identifier is an internal configurable default, not an Agent setting. Base64 is
requested so Azents validates bytes directly and does not fetch an untrusted or expiring
remote URL. A bounded URL-download fallback may be implemented only if a documented xAI
response omits Base64, and must enforce HTTPS, an xAI-owned host allowlist, redirect
limits, byte limits, timeouts, and media validation.

### Explicit source section: Fixture and prerequisite policy

Deterministic CI fixtures are required because external xAI OAuth entitlement, quota,
latency, and cost are not stable test prerequisites. Optional live validation may use a
retained test OAuth token without printing it. Missing live credentials skip only the
optional live test; deterministic behavior remains required and failing.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
