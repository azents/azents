---
title: "Direct File Transfer Implementation Plan"
created: 2026-09-29
tags: [files, runtime, implementation, plan]
---

# Direct File Transfer Implementation Plan

- Authority: [files-260929/REQ](../requirements/files-260929-direct-file-transfer.md), [files-260929/ADR](../adr/files-260929-direct-file-transfer.md), [files-260929/DESIGN](../design/files-260929-direct-file-transfer.md), approved revision `1` with exact IDs `M1`–`M8`.
- Design delta: `None`.
- Independent reviewer for **every** integrated phase: `/root/files-260929-reviewer` (one read-only reviewer, requested only by the primary agent after its integrated checks pass).
- Primary agent: `/root`; owns implementation, integration, validation, review resolutions, phase progression, and PRs. Bounded implementation helpers may own non-overlapping phase paths; the primary agent runs the integrated gates and requests the single assigned review.
- Delivery: seven sequential, reviewable stacked PRs; phase `n+1` starts only after phase `n` PR is open. Create all PRs before monitoring the stack's CI. Do not merge without an explicit merge request.

## Phase and Interface Map

| Phase | Branch | Approved mechanisms | Deliverable and interface boundary |
| --- | --- | --- | --- |
| 1/7 S3 foundation | `azents/files-260929-1-s3-foundation` from `main` | M3, M5, M7 | Signed, safe GET download metadata; compatible RustFS PUT/checksum/copy/GET and filename evidence, including a bounded 128 MiB exercise. No public/API behavior switch. |
| 2/7 Runtime direct PUT | `azents/files-260929-2-runtime-put` from phase 1 | M3, M7, M8 | Exact-attempt metadata-only Runner PUT ticket, ownership/generation fencing, bounded Runner HTTP PUT, trusted immutable finalize, Memory/Redis parity, Platform transfer egress/readiness; no feature consumer switched prematurely. |
| 3/7 Runtime direct GET | `azents/files-260929-3-runtime-get` from phase 2 | M1, M2, M6, M8 | Exchange/Artifact/managed `import_file`, all `run_tool_to_file` parts, and external inbound provider staging switch to Runner GET; preserve source identity and part-level failure. |
| 4/7 Runtime outbound consumers | `azents/files-260929-4-runtime-outbound` from phase 3 | M1, M3, M6, M7, M8 | Switch `present_file`, Runtime `channel_action`, `read_image`, and Workspace download preparation to verified direct Runner PUT; preserve semantic/provider limits. |
| 5/7 Chat browser PUT | `azents/files-260929-5-chat-upload` from phase 4 | M1, M4, M6, M7 | Authorized ticket/PUT/finalize Exchange lifecycle, Chat UI and generated public client, large-attachment model-input preflight; replace multipart body relay. |
| 6/7 Browser GET and policy | `azents/files-260929-6-download-policy` from phase 5 | M1, M5, M6, M7, M8 | Authorized Workspace/Exchange direct GET, safe filename/type, expiry-owned cleanup, common 128 MiB activation, remove old inbound Admin setting and regenerate affected clients; coordinated cutover and old-relay removal. |
| 7/7 Integrated journeys | `azents/files-260929-7-e2e-spec` from phase 6 | M1–M8 | Required cross-surface RustFS/browser/Runner E2E fixtures and absent-relay evidence, full validation, current Living Specs, matching Requirements/Design `implemented` dates, remove the temporary plan files after verification. |

Phase execution plans specify the exact owning paths, entry/exit checks, and context checkpoints. If a current Spec must change before phase 7 to stay truthful, update it in the behavior-changing phase and reserve phase 7 for the full integrated audit. An earlier phase may introduce only non-authoritative primitives until its approved replacement is enabled with a compatible deployment.

## Cross-Phase Contracts and Rollout

- Product ownership remains Exchange, Workspace, Runtime Transfer, or external provider as recorded in the Design. S3 ingress existence and a presigned URL are never product authorization.
- Preserve the exact active transfer attempt, current Runner generation, trusted manifest, consumer acknowledgement, immutable source publication, and cleanup ownership across backend, Runner, and UI boundaries. Never persist or log signed URLs or expose them to the model.
- No direct-only feature uses legacy Control/API body relay as a fallback. Migrate or reject incompatible deployments; do not silently activate 128 MiB on old components. Keep Redis optional with a matching Memory contract.
- Before activation, inventory retained Exchange objects over 128 MiB and customized inbound Admin values. Validate browser endpoint/TLS/CORS and Platform-owned Runtime storage egress under `direct`, `proxy_required`, and `no_network`, plus signed 128 MiB PUT/copy/GET compatibility. Preserve 20 MiB image input and current provider/admin outbound bounds.
- Changed proto/OpenAPI surfaces must regenerate clients/descriptors from source. API, persistent-state, migration, auth, failure, and retry checks belong to the phase owning the change; never rewrite executed migrations.

## Removal, Evidence, and Checkpoints

- Phase 3 removes approved inbound Control-to-Runner body-stream use for all three listed consumer groups and the unrelated generic 8 MiB rejection for these paths.
- Phase 4 removes approved Runner-to-Control body-stream use for the listed outbound consumers, while retaining the 20 MiB image and provider policies.
- Phase 5 removes Chat's multipart 20 MiB API body read and Web guard; it does not remove the ModelFile semantic bounds.
- Phase 6 removes the old Workspace 64 MiB/API response stream and Exchange API response stream, response-scoped Workspace EOF settlement, and independent external inbound 500 MiB Admin setting; preserve outbound settings.
- Phase 7 checks that no reachable specified feature calls old body relays, old tests assert only authoritative limits, current Specs describe actual behavior, and historical implemented snapshots remain unchanged.
- Each phase records changed interfaces, focused commands/results, removal searches, reviewer findings, E2E/fixture prerequisites, risk and follow-on work before commit/PR. The root performs full integrated checks and requests one read-only review from `/root/files-260929-reviewer` per stable phase diff.
- If implementation reveals a new material mechanism, product contract, fallback, or operational mode, return to Requirements/ADR/Design and explicit approval before proceeding; do not encode it as an implementation-plan choice.
