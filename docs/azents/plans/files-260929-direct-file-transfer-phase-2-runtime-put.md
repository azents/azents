---
title: "Direct File Transfer Phase 2 Runtime PUT"
created: 2026-09-29
tags: [files, runtime, implementation, phase-plan]
---

# Direct File Transfer Phase 2 Runtime PUT

## Phase Execution Plan

- Phase: `2/7 — exact-attempt Runtime direct PUT`
- Branch/base: `azents/files-260929-2-runtime-put` → `azents/files-260929-1-s3-foundation` (PR #1951).
- PR boundary: `Complete authenticated Runner-to-S3 upload transport and trusted immutable finalize in Runtime coordination; leave feature consumers on their existing path until phase 4.`
- Inputs: `files-260929/REQ` confirmed, `files-260929/ADR-D1`–`D6` accepted, approved `files-260929/DESIGN` revision 1 / IDs M1–M8, phase 1 signed GET and 128 MiB RustFS evidence.
- Deliverables: `Exact upload transport discriminator/admission, metadata-only dispatch, authenticated exact-attempt PUT ticket, Runner bounded upload with source identity and checksum, trusted S3 HEAD/checksum/immutable snapshot, Memory/Redis parity, generation/cancel/retry/cleanup, explicit Runtime endpoint egress and readiness.`
- Non-goals: `No feature-adapter switch, Chat/Workspace/Exchange API or browser activation, 128 MiB policy cutover, persistent URL, long-lived Runner storage credentials, or fallback to a Control byte relay on direct-only attempts.`
- Interfaces: `Runtime Transfer admission/record; Runner Control intent; RuntimeRunnerTransfer exact claim; trusted S3 ingress/source handles; existing verified-object consumer and attempt terminal/result contract. Public file APIs do not change.`
- Approved Design mechanisms: `M3`, `M7`, `M8`; `M1` only as an upper-bound admission constraint, not early product activation.
- Authority references: `files-260929/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`; `files-260929/ADR-D1`, `ADR-D3`, `ADR-D6`; approved `files-260929/DESIGN`; current Agent Runtime Control, Runtime Provider, and Workspace Upload Specs.
- Design delta: `None`
- Removal obligations: `None for feature paths until phase 4: remove upload body-stream *usage* only when its approved consumer is switched. Legacy upload RPC remains for currently unconverted paths; a direct-only attempt may never use it.`
- Absence verification: `Direct-only dispatch and Runner path never invoke UploadTransfer; no signed URL is persisted, logged, or placed in coordination intent; old consumers retain their existing behavior before cutover.`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Transfer domain and state parity | `/root` | `python/apps/azents/src/azents/runtime/transfer/{data,store,memory,redis,coordinator,object_store}*` | Approved Design | Exact typed upload attempt and trusted immutable-state lifecycle, cleanup ownership | Memory/Redis shared contract and race tests |
| Metadata protocol and server | `/root` | `proto/azents/runtime_control/v1/**`, `python/libs/azents-runtime-control/**`, `python/apps/azents/src/azents/runtime/control_protocol/grpc/{runner_transfer_server,transfer_coordinator_server}*` | Domain/stores | Authenticated attempt-bound PUT ticket, current generation and deadline fencing, server verification | Proto generation, auth/protocol/grpc integration tests, Ruff/ty |
| Runner upload | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/{transfer,grpc*}*` | Protocol | Bounded SHA-256 and stable local snapshot, direct S3 PUT, result reporting without body relay | Runner unit/integration cancellation/identity tests, Ruff/ty |
| Endpoint and readiness | `/root` | Runtime transfer/server settings, Kubernetes provider `network_enforcement.py`, provider config/tests, relevant Helm values/templates | S3/protocol | Explicit short-lived signing endpoint and Platform-owned S3 egress in restrictive modes, fail-closed readiness | Provider network-mode tests, settings and chart tests |
| Integrated verification | `/root` | Phase-owned paths and phase plan | Previous workstreams | Stable integrated behavior, absence evidence, bounded large-file exercise | Root-run full focused tests, docs validator, diff check, independent review |

- Integration order: `Transfer admission/store → protocol/server/S3 verification → Runner HTTP PUT → endpoint/network readiness → integrated verification/review → commit/stacked PR.`
- Independent review: `/root/files-260929-reviewer` performs one read-only review of the complete stable integrated diff; only `/root` requests review after it finishes validation.
- Final validation: `Root runs proto generation and descriptor drift check; azents, runtime-control, Runner, provider Ruff/type/focused tests; Memory/Redis parity including stale attempt, cancel, timeout and empty Redis; RustFS 128 MiB checksum/copy/GET and Runner PUT integration; docs validator, git diff --check, direct-only body-relay/URL absence search.`
- Scope-drift check: `Only M3/M7/M8 and bounded M1 preflight; no new transport fallback, product policy, frontend/API path, historical snapshot rewrite or unapproved operator mode.`
- Context checkpoint: `Record implemented metadata contract, exact store/Runner lifecycle and tests, egress readiness evidence, independent reviewer findings, unconverted feature paths, Phase 3 interfaces, and Design delta None.`

## Validation Checkpoint

- Exact direct-only upload attempt, dispatch and current Runner generation are fenced at claim, renewal, and completion. The claim persists a separate mutable ingress handle before signing; cancellation during signing does not return a capability and retains cleanup evidence. Signed URLs are transient response values, not stored in transfer state or dispatch.
- Runner snapshots a bounded, stable regular file and computes SHA-256 before its exact checksum-bound HTTP PUT. The direct-only branch returns before `UploadTransfer`; there is no Control byte-stream fallback. Control verifies native checksum-aware HEAD and copies the ingress to a distinct immutable final object before publication.
- Terminal ingress evidence remains pending until the later of PUT capability expiry and transfer deadline plus cleanup grace; Memory/Redis contract tests exercise retention past normal terminal TTL. Object-store deletion and record clearing are fenced separately for retry after interruption.
- Kubernetes Provider requires an exact object-storage Service role and validates configured endpoint authority when enabled; the chart preserves the pre-cutover null default and renders the additional Service-read RBAC and Provider endpoint. Runtime Control explicitly signs both internal/public S3 clients with SigV4: the default SigV2 PUT was rejected by real RustFS with `SignatureDoesNotMatch`.
- Root verification after review fixes: azents Runtime transfer/composition suites **334 passed**, Runtime Control client suites **26 passed**, Runner suite **38 passed**, Kubernetes Provider suite **120 passed**, Helm render suite **25 passed**, docs index validator suite **14 passed**; Ruff and type checks pass for all four Python projects. Protobuf regeneration changed no generated-file hashes; `git diff --check` passes.
- Isolated RustFS exercise: **128 MiB** SigV4 signed PUT, checksum-aware HEAD, multipart immutable copy, complete GET SHA-256 verification, and rejection of a wrong-checksum PUT passed. The temporary RustFS container was stopped and removed. This is storage-path evidence, not a claim that an end-to-end feature consumer is switched.
- Independent read-only review found three concrete gaps: HEAD could outlive the initial stream lease before the keeper started; direct-only admission lacked the M1 128 MiB ceiling; Runner buffered an unbounded successful PUT response. Root moved the lease keeper across HEAD and copy, fences expired direct-upload verification atomically in Memory/Redis, rejects direct-only 128 MiB + 1 at admission, and bounds the PUT response to 4096 bytes. A paused-HEAD renewal test, shared-store expiry test, admission boundary test, and oversized-response Runner test were added. Full root revalidation passed and the reviewer found no remaining violation in a bounded recheck.
- Isolated Runner→RustFS exercise: an actual 128 MiB file snapshot flowed through `RunnerTransferManager` to RustFS via a SigV4 checksum-bound PUT (no byte relay); the trusted test collaborator performed checksum-aware HEAD, immutable multipart copy, and final full GET digest verification. The temporary RustFS container was removed. This used a test Control/claim collaborator, not the deployed gRPC and Kubernetes data plane.
- Remaining rollout gate: the actual Runner→RustFS path in every restrictive Kubernetes network mode still needs deployment E2E evidence before feature-consumer cutover. Phase 4 still owns that cutover; no public file APIs or browser activation are changed in this phase.
