---
title: "Brave Search Native Toolkit Implementation Plan"
created: 2026-09-25
tags: [agent, toolkit, search, implementation]
---

# Brave Search Native Toolkit Implementation Plan

- Requirements: [brave-260925/REQ](../requirements/brave-260925-native-search-toolkit.md)
- Decision: [brave-260925/ADR-D1](../adr/brave-260925-native-search-toolkit.md)
- Approved Design: [brave-260925/DESIGN](../design/brave-260925-native-search-toolkit.md), revision `1`, IDs `M1`–`M6`
- Design delta: `None`
- Implementation/integration owner: `/root`
- Single independent reviewer for each integrated phase: `/root/brave-reviewer` (read-only)

## Delivery Shape

Three reviewable stacked PRs; each PR is opened before the next phase begins. Create the complete stack before monitoring CI; never merge without specific requester approval.

| Phase | Branch and base | Approved mechanisms | Review boundary |
| --- | --- | --- | --- |
| 1. Backend and file admission | `feature/brave-search-1-backend` from `origin/main` | M1–M5 | Native provider, direct typed Brave client, five tools, safe image download, ordered dual-file outputs, backend tests, design snapshot |
| 2. Management UI and API surfaces | `feature/brave-search-2-management` from phase 1 | M1, M3 | Toolkit management form, key redaction/edit and connection-test UX, generated clients if API contract changed, frontend tests |
| 3. E2E validation and promotion | `feature/brave-search-3-validation` from phase 2 | M1–M6 | Isolated testenv Brave transport/fixture, deterministic E2E and failure evidence, Living Spec promotion and approved snapshot implementation date, plan removal |

## Fixed Interfaces and Ownership

- Encrypted ToolkitConfig credentials remain the sole key authority. Registered provider executes on the worker, independent of managed Runtime; existing scope/revision and Tool Search control availability.
- Five separate native functions call only fixed Brave Search API endpoints; no Brave MCP service, provider-hosted `web_search` override, dynamic API URL from a model, or Runtime key injection.
- Image search retains original-image and source-page URLs as metadata; only validated fixed-host Brave-proxied thumbnails are downloaded by worker. FileOutputParts belong to the model path, AttachmentOutputParts to participant-visible Exchange.
- Client-generated-file admission uniquely keys multiple outputs by `(call_id, output_index)` within one call. Provider-generated image identity restrictions remain intact. Session/Run resource ownership and transactional persistence/cleanup remain authoritative.
- External Channel remains a separate explicit publication capability; no channel-specific Brave presentation logic.
- No new persistence table or migration is planned. Compare OpenAPI before regenerating source-derived clients; update impacted Specs after implementation evidence.

## Dependencies, Prerequisites, and Validation

1. Phase 1 establishes backend ToolkitType/registry, validated API client contracts, multi-image output semantics and secure fetch. Focused Python unit, credential, materializer, retry/cleanup and type/lint tests must pass before read-only review.
2. Phase 2 consumes stable backend config/credential schemas. Verify shared and Agent-only management, masked key updates, and explicit quota-bearing connection test. Run targeted frontend tests, lint, typecheck, and generated-client checks if a public OpenAPI contract changes.
3. Phase 3 supplies a testenv-only isolated Brave HTTP transport and deterministic responses/thumbnails without altering production endpoint or allowed proxy host. Required CI runs five-tool and Runtime-free/image/channel/failure E2E without a paid key, with recorded tool call counts, event parts, attachment URIs, model input and screenshots. Live Brave smoke is optional and skips without authorized credentials; required fixture mismatch fails, not skips.
4. Primary agent executes integrated validation per phase and requests the **same** read-only reviewer only after a stable integrated diff. Material findings are fixed and affected checks rerun. Run spec review immediately before the final QA/proof; update Toolkit, Conversation/file-exchange and execution Specs. Set `implemented` on Requirements and Design only after verified behavior. Remove temporary plans in final phase after promotion.

## Removal, Absence, Rollout, and Recovery

- Replace the one-image **client-tool** result admission and call-ID-only duplicate validation with ordered distinct output identities; preserve provider-image rejection. Absence evidence: two-image one-call and duplicate-rank tests, plus provider-image regression.
- Keep existing Toolkit, model-hosted Web search, Runtime, file lifecycle and External Channel contracts unchanged. No automatic channel publication, arbitrary original-image fetch, unbounded retry, or user-configurable provider base URL.
- Rollout is ordinary backend/UI release. Revoke/disable removes future availability via existing Toolkit lifecycle; a revoked key fails clearly on next contact. File storage failure compensates newly uploaded bytes and returns a failed tool result. Rollback removes new registry/UI while leaving inert string-typed ToolkitConfig rows; no destructive data migration.
- If discovery needs a user-visible contract change, return to Requirements; if it needs an unapproved material mechanism, return to ADR/Design and obtain renewed approval. Plans confer no additional authority.

## Context Checkpoints

- Phase 1 → 2: backend schemas, direct client and ordered output identities with focused tests; first PR open.
- Phase 2 → 3: management UX and any generated clients validated; second PR open.
- Phase 3 completion: required E2E and review evidence, current Specs, matching implementation dates, removed temporary plans; third PR open, monitor CI without merging.
