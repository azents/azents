---
title: "Runtime File Browser Upload Implementation Plan"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, workspace, frontend, implementation]
---

# Runtime File Browser Upload Implementation Plan

- Requirements: [fileupload-260917/REQ](../requirements/fileupload-260917-runtime-file-browser-upload.md)
- Decisions: [fileupload-260917/ADR](../adr/fileupload-260917-runtime-file-browser-upload.md)
- Approved Design: [fileupload-260917/DESIGN](../design/fileupload-260917-runtime-file-browser-upload.md)
- Approved Design revision: `1`
- Approved mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11, M12, M13, M14`
- Independent reviewer: `fileupload-reviewer`
- Design delta: `None`

## Delivery Shape

Ship three stacked PRs. Phase 1 establishes the complete internal direct-object
contract because S3 ticket/finalize semantics, Runtime Transfer claim, Runner HTTP
download, network authority, cleanup, and stores must agree before a public API can be
stable. Phase 2 fixes the generated JSON control API. Phase 3 owns browser hashing,
direct PUT progress/cancel, UI, E2E, Spec promotion, and plan cleanup.

### Phase 1/3: Runtime backend and direct object transfer

- Branch: `feat/upload-260917-1-runtime-backend`
- Base: `main`
- PR title prefix: `fileupload-260917 [1/3]: runtime direct object transfer`
- Scope: approved snapshot documents; S3 checksum/presign/finalize primitives;
  `WorkspaceUpload` operation and immutable delivery attempts; Memory/Redis parity;
  metadata-only internal create/finalize/status/cancel/retry RPCs; source cleanup and
  reconciliation; Runtime Transfer exact-attempt download claim; Runner direct HTTP
  download and atomic commit; conflict preconditions; public-endpoint readiness and
  Platform Runtime egress projection; complete focused tests.
- Mechanisms: `M1, M3, M4, M5, M6, M7, M8, M9, M10, M12, M14`.
- Boundary: no public HTTP routes, OpenAPI/generated public clients, FileBrowser UI, or
  browser E2E.

### Phase 2/3: Public JSON API and generated clients

- Branch: `feat/upload-260917-2-public-api`
- Base: Phase 1 branch.
- PR title prefix: `fileupload-260917 [2/3]: public upload control API`
- Scope: Agent Workspace create/finalize/status/cancel/retry service and routes;
  public-safe upload ticket, status, conflict, and error models; API-to-Runtime-Control
  client composition; OpenAPI dump; generated Python/TypeScript clients; route and
  authorization tests.
- Mechanisms: `M1, M2, M3, M4, M5, M8, M11, M12, M14`.
- Boundary: JSON control plane only. No application/octet-stream body route, Main Web
  binary proxy, FileBrowser controls, or new Runtime mechanism.

### Phase 3/3: Web direct upload, E2E, Specs, and cleanup

- Branch: `feat/upload-260917-3-web-e2e`
- Base: Phase 2 branch.
- PR title prefix: `fileupload-260917 [3/3]: workspace upload UI and E2E`
- Scope: generated-client control calls; bounded worker SHA-256; direct presigned PUT
  with progress and abort; FileBrowser picker/tray/conflict/cancel/retry; cache
  invalidation; four-locale copy; component/Storybook coverage; direct PUT/finalize/
  direct GET E2E across Runtime network modes; integrated quality; authority/removal
  audit; Living Spec promotion; implementation marking; plan cleanup.
- Mechanisms: `M2, M4, M5, M6, M8, M9, M11, M12, M13, M14`.
- Boundary: no new backend authority or transport mode; fixes remain within approved
  Design revision 1.

## Interfaces and Dependencies

- Phase 1 fixes opaque upload/source handles, object attribute and checksum contract,
  upload-operation CAS state, internal metadata RPCs, exact-attempt claim, Runner direct
  download, endpoint readiness, Runtime network authority, and cleanup semantics.
- Phase 2 fixes generated public control operations and public status/error unions.
- Phase 3 consumes those contracts, verifies the real browser/object-store/Runner path,
  and promotes current behavior to Living Specs.

No phase may add Exchange publication, durable PostgreSQL upload state, application byte
relay, browser reload resume, directory upload, archive extraction, implicit parent
creation, public bucket access, S3 credentials in Browser/Runner, URL persistence, or
mixed-version fallback.

## Ownership

| Workstream | Primary owner | Reviewer | Integration owner |
| --- | --- | --- | --- |
| Runtime backend, S3 contracts, Runner, Provider network authority | Root agent | `fileupload-reviewer` | Root agent |
| Public API/OpenAPI/generated clients | Root agent | `fileupload-reviewer` | Root agent |
| Main Web/FileBrowser/E2E/Specs | Root agent | `fileupload-reviewer` | Root agent |

The root agent requests one read-only review from `fileupload-reviewer` only after each
phase diff is integrated, validated, and frozen. The same reviewer covers all phases.

## Context Checkpoints

At every phase boundary record completed mechanisms, changed interfaces and paths,
focused and integrated validation, removal and absence evidence, remaining scope,
prerequisites, risks, exact reviewer result, and `Design delta: None`.

## Removal and Replacement

- Phase 1 removes the unmerged Main Web/API/Runtime Control body-stream foundation:
  internal `UploadWorkspaceSource`, Workspace source multipart writer, Workspace
  source-to-transfer-object copy, and Workspace `DownloadTransfer` consumption.
- Phase 1 retains and adapts upload operation/store/reconciliation, conflict evidence,
  atomic commit, and cleanup where they satisfy approved mechanisms.
- Phase 2 proves no public binary content route or handwritten duplicate backend
  contract exists.
- Phase 3 proves Browser bytes go directly to S3, removes obsolete old-snapshot plans
  and code references, promotes Specs, and marks only `fileupload-260917` implemented.

## Validation Matrix

- Phase 1: proto generation; S3-compatible checksum, presign, conditional-copy, cleanup,
  and readiness tests; Runtime Control/Runner/Provider/az-common Ruff, format, type
  checks, Pytest; Memory/Redis store contracts; deterministic claim/cancel/generation/
  conflict/reaper tests; Helm render/schema tests; docs validation; absence searches.
- Phase 2: OpenAPI dump and generated diff; Python Ruff/type/Pytest; generated Python and
  TypeScript client checks; authorization, concealment, conflict, and public mapping
  tests; absence of binary body routes.
- Phase 3: TypeScript format/lint/typecheck/build/tests; Web Worker/hash/direct PUT tests;
  Storybook interactions; required browser E2E against compatible object storage and
  direct/proxy/no-network Runtimes; exact-byte Workspace download; spec-review; docs
  validation; full authority and removal audit.

## Fixtures and Prerequisites

Use the existing Docker Runtime Provider, Runtime Control, Runner, and RustFS/S3 fixture.
Extend it with browser-visible public endpoint, Main Web CORS, Runner-reachable endpoint,
checksum-enabled HEAD, conditional native copy, deterministic URL expiry, direct PUT
inspection, and Platform egress fixtures. Record object-store implementation/version and
endpoint mode in E2E evidence. No live provider credential is required for required CI.

## Spec and Rollout Impact

Phase 3 updates Workspace, Agent Runtime Control, Runtime Provider/network enforcement,
and File Exchange Storage Living Specs as applicable. Workspace Upload fails closed
until public endpoint, CORS, checksum/copy compatibility, Runtime Control, Runner, and
network authority all support revision 1. Rollback hides/removes the feature controls;
unfinalized objects expire and cleanup converges, while committed Workspace files remain
ordinary user filesystem state.

## Blockers

Implementation is conditional on the configured S3-compatible fixture supporting signed
SHA-256 upload checksums, checksum attributes, source-fenced native copy, browser CORS,
and a stable enforceable Runner route in every required network mode. A failed
compatibility test is a blocker, not authority for a byte-relay fallback.

Any new material behavior, state, configuration mode, source of truth, fallback, or
public contract returns to `technical-feature-design` for reapproval.

## Plan Cleanup

Phase 3 removes this plan and every phase plan only after implementation, integrated
validation, independent review, Spec promotion, and matching `implemented` dates on the
final Requirements and Design.
