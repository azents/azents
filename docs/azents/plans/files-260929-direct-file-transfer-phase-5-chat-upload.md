---
title: "Direct File Transfer Phase 5 Chat Browser PUT"
created: 2026-09-29
updated: 2026-09-30
tags: [files, chat, browser, implementation, phase-plan]
---

# Direct File Transfer Phase 5 Chat Browser PUT

## Phase Execution Plan

- Phase: `5/7 — authorized browser PUT and verified Chat Exchange finalize`
- Branch/base: `azents/files-260929-5-chat-upload` → `azents/files-260929-4-runtime-outbound` (PR #1959).
- PR boundary: `Replace Chat multipart file-body relay with authorized upload preparation, browser PUT and verified finalize, preserving the existing final Exchange attachment response and message/root claiming. Accept files through 128 MiB without forcing oversized originals into model input.`
- Inputs: [files-260929/REQ](../requirements/files-260929-direct-file-transfer.md), [files-260929/ADR](../adr/files-260929-direct-file-transfer.md), [files-260929/DESIGN](../design/files-260929-direct-file-transfer.md) revision 1 / M1–M8; reviewed S3 native-checksum/immutable-promotion primitives and Runtime consumer phases 1–4.
- Deliverables: `Current requester/Agent authorization at preparation and finalize; an opaque operation bound to expected size, SHA-256, filename/media type and private owned ingress; a transient exact-object PUT ticket; trusted checksum/size verification and immutable Exchange source before attachment publication; bounded failed/abandoned ingress cleanup; 128 MiB Chat UI acceptance and finalized-only attachment state; metadata-first model-input eligibility without reading an ineligible large original.`
- Non-goals: `No new durable product file identity, automatic Workspace destination, browser GET redirect, provider/admin limit migration, arbitrary object key, long-lived browser credential, relay fallback, new layout, or relaxed model-input policy.`
- Interfaces: `Feature-owned upload prepare/finalize API and opaque operation manifest; existing S3 presigning/checksum/immutable copy; Exchange Agent upload authorization and publication; current UploadResponse fields; generated public clients; Chat useFileUpload state; reusable bounded worker SHA-256; accepted user-attachment promotion and Session-root claiming.`
- Approved Design mechanisms: `M1` for browser upload eligibility, `M4`, `M6`, existing `M7` reachability/CORS prerequisites.
- Authority references: `files-260929/REQ-1`–`REQ-6`, `files-260929/ADR-D1`, `ADR-D4`, `ADR-D6`, approved `files-260929/DESIGN`, current File Exchange Storage and Chat input Specs.
- Design delta: `None`.
- Removal obligations: `Remove Chat UploadFile/multipart complete-body read and the matching 20 MiB web/API transport guard on this feature. Update clients and tests to the prepare/PUT/finalize contract. Retain independent model-input, image, unrelated multipart upload and five-file-selection limits.`
- Absence verification: `Search the Chat upload route/hook for multipart FormData, UploadFile/file.read and old transport bounds; show browser PUT goes to the owned S3 endpoint, API requests contain metadata only, no attachment publishes before trusted finalize, and large attachment promotion never opens its original body when metadata already proves model-input ineligibility.`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Authorized upload lifecycle | `/root` (bounded metadata repository/model/migration: `/root/direct-get-core`) | `python/apps/azents/src/azents/services/chat/`, `services/exchange_file/`, related feature-owned repositories/lifecycle/cleanup support and tests | Approved M4 and S3 primitives | Exact owner/Agent/manifest operation, current authorization, verified immutable Exchange publication, idempotent finalize and bounded cleanup | Auth, wrong owner, expired operation, manifest mismatch, replay/concurrent finalize, cleanup and no-publication-on-failure tests |
| Public API/client contract | `/root` | `python/apps/azents/src/azents/api/public/chat/v1/**`, OpenAPI and generated Python/TypeScript public clients | Lifecycle interfaces | Metadata-only prepare/finalize; existing final attachment response; old Chat body relay removed | API contract/auth/status tests, generated drift, OpenAPI client regeneration |
| Browser direct upload | `/root/phase3-explicit-mode` (root integrates) | `typescript/apps/azents-web/src/shared/file-upload/**`, metadata-only Next routes, reusable hashing worker and current Workspace hashing imports/tests, relevant Chat locales/tests | Public contract | Bounded worker digest, exact signed PUT, finalize before done, retained pending/error/retry/removal and five-file behavior | Hook/worker tests, 128 MiB boundary, signed headers, cancellation/error/finalize state, unchanged layout and localized examples |
| Large attachment model preflight | `/root` | Existing accepted-attachment/model-input promotion services and tests | Verified Exchange metadata | Eligible small files retain current promotion; large accepted attachment retains metadata/download/import without complete original read | Metadata-only eligibility, no body read for ineligible originals, normal small-file/root claiming regressions |
| Integrated verification/review | `/root` (new service/API tests: `/root/direct-get-core`; product E2E: `/root/direct-get-research`) | Phase-owned paths and this plan; required browser/API E2E/fixtures as needed | All workstreams | Browser/RustFS create→PUT→finalize evidence, large-attachment message safety and stable generated clients | Root backend/TypeScript full checks, actual product E2E, no-relay/URL-state evidence, assigned independent review |

- Integration order: `Inspect current authorization, publication and message promotion → implement exact upload lifecycle/cleanup → metadata API and generated clients → reusable bounded hashing and Chat PUT/finalize hook → metadata-first model-input preflight → root integration/E2E → assigned review → commit/stacked PR.`
- Independent review: `/root/files-260929-reviewer` reviews the stable complete phase read-only only after root final validation. Root alone requests review, implements required findings and reruns affected checks.
- Final validation: `Root backend Ruff/format/ty/full pytest, public contract and checksum/immutable storage tests, full relevant TypeScript format/lint/typecheck/build/tests, regenerated OpenAPI/client drift, actual browser/API/RustFS upload journey, oversized attachment message without original-body read, doc/pre-commit and git diff --check. Record fixture prerequisites and distinguish optional live tests from verified product journeys.`
- Scope-drift check: `Only M1/M4/M6 and existing M7 prerequisites. Preserve existing Exchange retention, upload owner and Agent scope, Session-root claiming, final attachment fields, small-file model behavior, image20MiB and provider policies. No new material transport, authority, product identity or fallback. Phase 6 retains browser GET and coordinated common/Admin policy migration; Phase 7 retains full integrated deployment/network coverage and Spec promotion.`
- Context checkpoint: `Record prepare/finalize contract, operation manifest and expiry/cleanup ownership, immutable-source evidence, UI/hash/cancel behavior, generated surfaces, model-input no-read boundary, commands/E2E evidence, assigned review, risks and next-phase inputs. Keep the exact reviewer and stack bases.`

## CI Repair Execution — September 30, 2026

- Root owns the complete stack's CI correction; `Design delta: None`. This refines existing M1/M4/M6 verification under the global load-tests-as-reports convention and the requester's explicit lowered-limit instruction.
- `/root/direct-get-core` owns only the already-reviewed Config gate/default, canonical 128 MiB constant, Chat prepare admission, and matching unit tests. `/root` owns small required E2E boundaries, scenario-specific request evidence, testenv fixture injection, this plan, integrated checks and GitHub/stack operations.
- Production upload remains 128 MiB. Gated test-only injection is positive and lowering-only. Unit tests use 15/16/17 bytes at 16 bytes; integrated Chat uses a 1 MiB cap so its existing independent 1,000,000-byte model-budget warning remains exercised. Real storage protocol bodies use 32 KiB. No Admin setting, image/model/provider change, TLS relaxation in product, or later-phase GET behavior is added here.
- Required removal: the two actual 128 MiB recurring bodies. Existing completed heavyweight evidence remains in the Phase 7 supporting report; routine suite execution must not repeat it.
- Integration: finish backend and E2E work → root Ruff/format/ty and focused backend/product/storage/browser validation → freeze correction → root requests `/root/files-260929-reviewer` read-only review → correct findings and rerun affected checks → normal Phase 5 follow-up commit → rebase dependent phases through the repository script → replay Phase 6 consumer/download fixes → validate/review → synchronize Phase 7 and verify its final tree → push all phases before waiting on CI.
- Absence proof: search required file journeys for actual 128 MiB bodies/test names; metadata-only schema-ceiling probes remain allowed. Explicitly preserve authorization, checksum/publication, idempotency, model-budget warning and browser completion.
- Phase 6 owns generic consumer propagation and TLS-fixture-only GET verification. Phase 7 owns final Specs/report/plan cleanup. Do not revive deleted plans or modify implemented snapshots while synchronizing later branches.

## Entry Checkpoint

- Phase 4 PR #1959 is open at `5bc0c6f76`; the current registered worktree was clean when this Phase 5 branch was created.
- Existing Chat `/agents/{agent_id}/upload` reads multipart bytes under 20 MiB and creates an Agent-scoped Exchange upload. Its final response already supplies attachment ID, URI, media type, size and name. Existing authorization/publication must be reused rather than treating S3 existence as permission.
- Main Web `shared/file-upload/useFileUpload.ts` has a five-file bound and a 20 MiB upload guard. Existing Workspace `workspaceUploadHash.ts` provides an explicit cancellable dedicated worker with bounded File.slice reads; share that mechanism without importing feature-owned code into the shared layer.
- REQ-6 explicitly requires accepted large attachments to remain usable even when not eligible as complete model input. Metadata must establish eligibility before opening the original object; this does not authorize dropping the attachment or relaxing model policy.

## Implementation Checkpoint

- The metadata-only prepare contract is `POST /chat/v1/agents/{agent_id}/uploads`
  with `{filename, media_type, size, sha256}`. It returns an opaque `upload_id`
  and transient `put_url`, `put_headers`, and `expires_at`; responses are
  `Cache-Control: no-store`. Finalize is
  `POST /chat/v1/agents/{agent_id}/uploads/{upload_id}/finalize`, retaining the
  existing attachment response fields.
- The operation binds uploader, current Agent/workspace scope, manifest and
  reserved source/preview publication IDs. It persists no URL or Runtime
  identity. Current authorization is checked at prepare, claim, retry load and
  atomic publication. Finalized retry returns only the existing authorized
  publication, never recreates a removed attachment.
- PUT signatures bind exact content length, checksum and content type. Scripts
  receive checksum/content-type headers only: browsers supply the signed
  Content-Length from the immutable File body.
- Capability lifetime is five minutes, operation lifetime fifteen minutes,
  finalize claim/timeout five minutes, and cleanup eligibility fifteen minutes
  after operation expiry. Native checksum-aware HEAD gates an immutable
  operation-owned source; verified native copy gates final Exchange publication.
  A still-live PUT can only mutate ingress, never the source or publication.
- Cleanup is a bounded existing file-lifecycle scheduler pass. Durable claims
  survive deleted product owners, fence delayed finalizers, abort exact-key
  incomplete copies, and delete temporary ingress/source. Only a never-finalized
  operation permits cleanup of reserved uncommitted product/preview objects.
  A failed cleanup leaves its durable operation eligible for lease retry.
  Completed operations retain ownership evidence and become due for bounded
  re-cleanup one hour later: a PUT started before signature expiry may finish
  after the first grace pass. Exact claims, a full due index and advancing
  cleanup deadlines keep late residues collectible without authorizing new
  publications or introducing a second ownership oracle.
- The required E2E fixture previously configured only API-internal RustFS DNS.
  Browser/API direct PUT validation requires an explicitly reachable public
  signing endpoint; fixture configuration is corrected without a new relay or
  signed-URL host replacement.
- Final root validation: backend Ruff/format/ty passed; full application suite
  **6,134 passed, 3 existing skips**; `az-common` **69 passed** with static checks;
  focused operation/service/API **109 passed**; migration single-head,
  base-to-head upgrade and model/DDL checks **3 passed**. The linear migration
  head is `0c18705eb6cb`; the already-executed initial `9462aab292cc` is unchanged.
- Final frontend validation: Web **304 passed** and the complete TypeScript
  monorepo format/lint/typecheck/build passed. Unmount cancels every queued
  snapshot ID before cancelling active tasks, preventing a subsequent upload
  after the composer is gone. Workspace progress/cancellation is unchanged.
- OpenAPI and both public clients were regenerated using repository commands;
  the old Chat multipart operation and browser/API transport guard are absent.
- Fresh final credential-free product E2E: **13 passed, 6 existing skips**
  (12 API tests and one real-browser journey), using migration
  `0c18705eb6cb`, backend image `azents-e2e:74d66517dba1835c`, Main Web
  `azents-web-e2e:e185532d68ea4b54` and Admin Web
  `azents-admin-web-e2e:c090a6ae566e04fa`. Proof includes inclusive native
  128 MiB PUT/checksum/immutable publication, actual large-attachment message
  retention with a bounded model-budget warning, current auth/retry/no-relay
  checks, and real UI Worker → metadata prepare → File PUT/CORS → finalize →
  exact authorized download. Existing skips concern Session Exchange listing.
- Full E2E Ruff/format/ty also passed. Commit-hook validation caught two
  existing primitive-test callers missing the now-required exact content length;
  both now pass the real body size explicitly. The complete native RustFS
  transfer-storage suite then passed **6 tests**, including bounded 128 MiB
  PUT/copy/GET. These mechanical test-call corrections change no product code.
- Final E2E evidence is retained as Session-local
  `phase5-final-e2e-retry.log`, `.xml` and
  `phase5-final-e2e-retry-artifacts/browser/chat-direct-upload-evidence.json`.
  The browser evidence retains only safe metadata, hashes and statuses; no
  signed URL or file body. S3 gateway access logging is disabled in the fixture.
- A runtime Docker cache reset exposed a pre-existing GHCR auth failure while
  fetching the pinned public UV image. Isolated anonymous Docker configuration
  restored the exact pinned prerequisite; global auth, Dockerfiles, daemon and
  product behavior were not changed. Final E2E passed after fresh rebuild.
- Assigned independent read-only review by `/root/files-260929-reviewer` is
  **approved**, with no required correctness, security, data-loss, material
  interface or convention findings. The reviewer inspected the complete phase
  diff, new files and safe browser evidence, acknowledged root verification,
  and did not edit code or independently rerun the full suites.
- Phase 6 keeps browser GET and coordinated common/Admin policy cutover;
  Phase 7 keeps Spec synchronization, final deployment/network coverage,
  coordinated-release proof and plan cleanup.
