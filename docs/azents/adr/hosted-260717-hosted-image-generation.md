---
title: "Provider-Hosted Image Generation Restoration Historical Decision Reconstruction"
created: 2026-07-17
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: hosted-260717
historical_reconstruction: true
migration_source: "docs/azents/design/provider-hosted-image-generation.md"
---

# Provider-Hosted Image Generation Restoration Historical Decision Reconstruction

- Snapshot: `hosted-260717`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/provider-hosted-image-generation.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### hosted-260717/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: 1. Restore one semantic builtin contract

Add `image_generation` to the implemented builtin registry. The registry entry has no historical Gemini-specific rule. Generic model-option validation verifies that the selected model snapshot advertises `image_generation`.

All hosted-tool dispatch becomes exhaustive:

- `web_search` uses the existing translation;
- `image_generation` uses the image-generation translation;
- any registered semantic builtin without a lowerer implementation raises `UnsupportedRequiredBuiltinToolError`;
- any selected builtin missing from the selected model capability raises before provider dispatch.

The semantic config remains an open JSON object whose accepted keys are provider-contract fields such as quality, size, format, background, or partial image count. Each lowerer passes only fields accepted by its native target validation. Invalid config fails preparation rather than being removed.

### Explicit source section: Fixture and CI policy

The deterministic fixture is required in normal CI and must fail rather than skip. It uses a committed small image fixture and provider-stream snapshots with no credentials.

Optional live-provider smoke tests may run for OpenAI API and ChatGPT OAuth when credentials and account capability are present. They skip only when prerequisites are absent. Once prerequisites are present, provider rejection, missing attachment, or raw-payload leakage fails the test.

Validation evidence should include:

- focused backend test output;
- OpenAPI/schema diff showing no raw-image field;
- E2E logs for all three runtime paths;
- a downloaded attachment checksum;
- an assertion over serialized durable history and live payloads proving the Base64 fixture substring is absent.

### Explicit source section: Final Decisions

- One restoration covers OpenAI SDK, ChatGPT OAuth, and LiteLLM.
- Generated image bytes remain transient until stored in Exchange and ModelFile object storage.
- A successful provider-tool result contains both a ModelFile-backed FilePart and an Exchange-backed Attachment.
- The database never stores Base64 or raw image bytes.
- Later model calls rehydrate the ModelFile only in request-local memory.
- Output admission is strict: partial materialization is failure.
- Historical Gemini-specific validation conditions are not part of the restored contract.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
