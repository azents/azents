---
title: "Runtime File Browser Upload Phase 1 Runtime Backend"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, implementation, phase-plan]
---

# Runtime File Browser Upload Phase 1 Runtime Backend

## Phase Execution Plan

- Phase: `1/3 — Runtime backend and direct object transfer`
- Branch/base: `feat/upload-260917-1-runtime-backend` → `main`
- PR boundary: `Complete the approved internal direct-object Workspace Upload contract without public API or Web surface`
- Inputs: `fileupload-260917/REQ`, accepted `fileupload-260917/ADR-D1` through `D9`, approved `fileupload-260917/DESIGN` revision `1`
- Deliverables: `S3 direct-ingress ticket/finalize primitives; typed WorkspaceUpload operation and immutable delivery attempts; Memory/Redis parity; metadata-only internal coordinator RPCs; exact source cleanup/reconciliation; Runtime Transfer direct-object claim; Runner HTTP download and atomic commit; conflict preconditions; mandatory public-endpoint readiness and Platform Runtime egress; focused integrated tests`
- Non-goals: `Public HTTP/OpenAPI routes, generated public clients, Main Web/FileBrowser UI, browser E2E, Spec promotion, direct implementation of later phases`
- Interfaces: `Opaque ingress/source handles; presigned PUT ticket metadata; checksum/size/ETag finalization; WorkspaceUpload CAS/store contract; internal create/finalize/get/cancel/retry RPCs; direct-object transport discriminator; exact-attempt claim RPC; Runner terminal result; Runtime object-storage endpoint authority`
- Approved Design mechanisms: `M1, M3, M4, M5, M6, M7, M8, M9, M10, M12, M14`
- Authority references: `fileupload-260917/REQ-2` through `REQ-6`; `fileupload-260917/ADR-D1` through `D9`; current Runtime Transfer, Agent Runtime Control, Runtime Provider, and Redis Specs`
- Design delta: `None`
- Removal obligations: `Remove unmerged UploadWorkspaceSource body RPC/client/server; Workspace source multipart body writer; Workspace source-to-transfer-object copy; Workspace use of DownloadTransfer; obsolete old-snapshot plan authority. Retain only mechanisms authorized by fileupload-260917.`
- Absence verification: `Generated descriptors and repository search contain no Workspace source-body RPC; Workspace flow has no body iterator, transfer-object copy, DownloadTransfer call, URL persistence, public route, Exchange entity, or PostgreSQL upload row`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved baseline and removal map | Root agent | `docs/azents/{requirements,adr,design,plans}/**file*upload*` | Approved Design | Final authority references, phase contract, obsolete mechanism inventory | Snapshot validator, authority audit, diff check |
| S3 presign and immutable finalize primitives | Root agent | `python/libs/az-common/src/azcommon/infra/s3/**`, tests | D2, D3, D9 | Signed checksum PUT/GET, checksum-enabled attributes, exact source-fenced copy, opaque identity helpers | az-common Ruff/type/Pytest plus compatible-store integration |
| Upload domain and stores | Root agent | `python/apps/azents/src/azents/runtime/transfer/workspace_upload*.py`, store/config tests | S3 contracts | Direct-ingress operation phases, ticket/finalize evidence, immutable delivery attempts, cleanup CAS, Memory/Redis parity | Domain and shared store contract tests |
| Internal metadata protocol | Root agent | `proto/azents/runtime_control/v1/**`, `python/libs/azents-runtime-control/**`, Runtime Control gRPC auth/server/client tests | Domain/store | Metadata-only create/finalize/get/cancel/retry and exact-attempt download claim; generated clients | Proto generation, library type/tests, auth boundary tests |
| Finalize, reconciliation, and cleanup | Root agent | Runtime Control Workspace upload coordinator/composition/reaper | S3/store/protocol | HEAD/checksum verify, native immutable snapshot, delivery creation, result projection, expiry, cleanup and orphan pagination | Deterministic CAS/lease/race/integrity/expiry/reaper tests |
| Direct Runtime delivery and conflict fencing | Root agent | Runtime transfer coordinator/data/store/result, Runner transfer domain/proto | Protocol/finalize | Direct-object transport mode, exact claim, retained admission/generation/cancel/result authority, opaque conflict evidence | Memory/Redis/coordinator/result tests and existing transfer regression |
| Runner HTTP download | Root agent | `python/apps/azents-runtime-runner/src/azents_runtime_runner/transfer.py`, HTTP collaborator and tests | Claim protocol | Redacted bounded GET, byte-zero renewal, SHA/size verification, cancel, temp cleanup, atomic commit | Ruff/type/Pytest with deterministic local HTTP fixture |
| Endpoint readiness and Runtime network authority | Root agent | Runtime Control settings/composition; Kubernetes Provider network enforcement; Helm chart/schema/render tests | Public endpoint contract | Mandatory public endpoint, Runtime Control signer, direct/proxy/no-network exact Platform egress, fail-closed readiness | Provider tests, Helm tests, config/composition tests |
| Integrated removal and validation | Root agent | All phase-owned paths | All workstreams | Stable Phase 1 diff with obsolete byte-relay mechanisms removed | Full phase matrix, absence search, generated drift, docs validation |

- Integration order: `baseline/removal inventory → S3 contracts → domain/store → metadata protocol → finalize/reconciliation → direct transfer claim → Runner HTTP → network/readiness → integrated removal and validation`
- Independent review: `fileupload-reviewer; root requests one read-only review only after all workstreams are integrated, final validation passes, removal searches pass, and the diff is frozen`
- Final validation: `Root runs git diff --check; docs validator; proto generation/diff; az-common, azents-runtime-control, azents, azents-runtime-runner, and Kubernetes Provider Ruff/format/type checks and focused Pytest; Memory/Redis shared contracts; Helm schema/render tests; S3-compatible direct PUT/finalize/direct GET integration; absence searches for UploadWorkspaceSource, Workspace body proxy, Workspace DownloadTransfer, transfer-object copy, URL logging/storage, Exchange, and RDB upload state`
- Scope-drift check: `Every retained or new mechanism maps to M1/M3/M4/M5/M6/M7/M8/M9/M10/M12/M14; no public route, Web UI, browser hashing, new persistence authority, fallback, optional mode, or later-phase behavior is added`
- Context checkpoint: `Record completed direct-object internal behavior, exact Phase 2 interfaces, generated surfaces, S3/provider prerequisites, removals and absence evidence, integrated commands/results, reviewer result, remaining public/Web/E2E scope, risks, and Design delta None`
