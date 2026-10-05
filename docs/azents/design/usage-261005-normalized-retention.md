---
title: "Normalized Usage Retention Design"
created: 2026-10-05
tags: [engine, usage, performance]
document_role: primary
document_type: design
snapshot_id: usage-261005
---

# Normalized Usage Retention Design

## Design Authority

Revision: 1.

| Mechanism | Classification | Confirmed authority |
| --- | --- | --- |
| M1: Durable usage models and serde contain only normalized accounting | decided | [usage-261005/ADR-D1](../adr/usage-261005-normalized-retention.md#d1--native-receipts-are-transient-normalized-usage-is-durable), usage-261005/REQ-1 and REQ-2 |
| M2: All adapter normalization paths pass transient receipts explicitly into the existing pricing decoder | required | usage-261005/REQ-3; existing captured-price, unknown/null and provider-quantity semantics |
| M3: Public schemas and Context projections omit receipt fields | required | usage-261005/REQ-2 |
| M4: No historical physical rewrite, added archive or compatibility fallback | decided | usage-261005/ADR-D2, usage-261005/REQ-4 |

## Mechanisms

Remove `raw` and `raw_hidden_params` from `TokenUsagePayload` and the engine run usage value. Existing normalized fields and typed cost provenance are unchanged. Repository model dumps therefore cannot write receipt data into new usage markers. The existing JSON serde writes/reads normalized run usage only.

Official OpenAI, generic Responses and Pydantic AI normalizers retain their native usage dictionaries locally. `apply_model_usage_pricing` accepts a required explicit `raw_usage` boundary parameter, consumes directed cache/media evidence using its existing decoder, then returns only the durable normalized payload. This is a lifetime split, not a second opaque receipt model or a cache.

Context and event projections serialize the typed normalized payload. Existing Pydantic payload parsing ignores removed JSON extras, so historical accounting remains readable without resurrecting receipt fields. Physical JSONB storage remains untouched. Both OpenAPI specifications and Python/TypeScript clients are regenerated. Frontend usage components already consume scalar values, so no layout or component replacement is needed.

## Removal and Replacement

- Durable receipt fields and serde raw writes: removed under ADR-D1; replaced by unchanged normalized token/cost/provenance fields. Verify schema/dump absence and old-record reserialization tests.
- Adapter receipt attachment to usage: removed; receipt remains a local normalization/pricing input under M2. Verify provider-specific counters and cost/null tests.
- Context inspector documentation of durable raw usage: replaced by normalized accounting contract under M3. Generated API schemas omit the removed fields.
- Receipt-oriented usage assertions/fixtures: replace with normalized results and absence assertions; provider response fixtures retain receipts as realistic ingress evidence.
- Historical physical bytes: retained boundary under ADR-D2. No data migration, DB cleanup, raw placeholder, separate archive or legacy fallback.

## Test Strategy

Primary end-to-end behavior is unchanged scalar usage presentation; the existing required E2E CI remains the product-regression gate. This bounded storage-contract change is primarily verified at typed admission, provider normalization/pricing, serializer and generated API boundaries, where receipt extras can be supplied deterministically without live provider credentials.

Matrix: OpenAI SDK unknown attribution extras; generic Responses reported charge; Anthropic cache-inclusive totals/TTL writes; Google reasoning/media quantities; Bedrock cache counters; missing/malformed quantity evidence; normalized marker/serde reserialization; public schema absence; web/admin usage consumers with regenerated clients.

No new testenv service or credential prerequisite is required. Existing fixture receipts remain available for ingress normalization. Run focused and full backend pytest/Ruff/ty, OpenAPI/client generation, frontend node tests and fresh lint/typechecks; retain content-free command outcomes in the Session report and PR. Required CI failures must be fixed; live-provider tests are not required and must not be substituted with claims of live verification.

## Design Approval

Mode: direct implementation of the requester's confirmed removal proposal, without intermediate approval pauses.
Decision owner: requester for durable retention scope; implementing Agent for equivalent internal boundaries.
Date: 2026-10-05. Approved revision: 1. Authority IDs: M1, M2, M3, M4.
Material scope: remove future durable usage receipts and their public projections after normalization/pricing; preserve normalized semantics; no historical deletion or operational deployment.
