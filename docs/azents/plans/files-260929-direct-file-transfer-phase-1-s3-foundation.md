---
title: "Direct File Transfer Phase 1 S3 Foundation"
created: 2026-09-29
tags: [files, runtime, implementation, phase-plan]
---

# Direct File Transfer Phase 1 S3 Foundation

## Phase Execution Plan

- Phase: `1/7 — S3 foundation and compatibility evidence`
- Branch/base: `azents/files-260929-1-s3-foundation` → `main`
- PR boundary: `Reusable narrowly signed GET response metadata and real S3-compatible checksum/filename/128 MiB evidence; no user-facing transfer cutover`
- Inputs: `files-260929/REQ` confirmed; `files-260929/ADR-D1`–`D6` accepted; `files-260929/DESIGN` revision `1`, exact `M1`–`M8`, approved on 2026-09-29.
- Deliverables: `Extend S3Service presigned GET to support trusted safe response filename and content type; retain exact-object and short-lived authority; verify RustFS signed GET metadata and 128 MiB single-PUT checksum/immutable-copy/GET flow using bounded-memory test payloads.`
- Non-goals: `No Runtime PUT/GET protocol, browser API route, feature consumer switch, 128 MiB general-policy activation, Admin setting change, or byte-relay fallback.`
- Interfaces: `S3Service.get_download_request and underlying signer accept optional validated response metadata without changing existing callers; signed response controls are derived from trusted file metadata, never user-supplied storage keys.`
- Approved Design mechanisms: `M3`, `M5`, `M7`
- Authority references: `files-260929/REQ-2`, `REQ-5`; `files-260929/ADR-D3`, `ADR-D5`; current Workspace Upload direct-object integrity precedent and `files-260929/DESIGN`.
- Design delta: `None`
- Removal obligations: `None in this pre-cutover phase; old body relays remain only for existing paths until their owned replacement phase.`
- Absence verification: `No public route, Runtime Control RPC, transfer dispatch, provider policy, or browser path switches in this diff.`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Approved snapshot and plan | `/root` | `docs/azents/{requirements,adr,design,plans}/files-260929*` | Requester approval | Revision-bound approval and phase contract | Docs validator, authority audit, link/diff checks |
| GET signing contract | `/root` | `python/libs/az-common/src/azcommon/infra/s3/service.py`, `service_test.py` | Approved M5 | Safe optional S3 GET response metadata signature and existing-call compatibility | az-common focused Pytest, Ruff, type check |
| Compatible-store evidence | `/root` | `testenv/azents/e2e/src/tests/required/test_runtime_transfer_storage.py`, directly necessary fixtures | GET contract | RustFS metadata GET and bounded-memory 128 MiB signed PUT/copy/GET evidence | Focused RustFS required E2E; explicit prereq failure if Docker unavailable |
| Integration and absence checks | `/root` | Phase-owned paths | Prior workstreams | Stable diff and result handoff | Root-run quality checks and targeted search |

- Integration order: `Approval/authority baseline → S3 signing contract and focused tests → RustFS-compatible tests → root integrated validation → independent read-only review → corrections/checks → commit and phase PR.`
- Independent review: `/root/files-260929-reviewer`; only `/root` requests review after all integrated work and checks are stable.
- Final validation: `Root runs docs validation and relative links, git diff --check, az-common Ruff/type/focused Pytest, the RustFS required focused test when its prerequisite is available, and an absence scan of phase-owned changes for unauthorized API/protocol/policy activation.`
- Scope-drift check: `M3/M5/M7 only; no new policy mode, writable capability, alternate data path, permanent signed URL, GET behavior regression, or later-phase changes.`
- Context checkpoint: `Record safe signing contract, RustFS test/evidence and environmental prerequisites, reviewer finding resolution, remaining Runner/API/browser work, and Design delta None before opening the PR.`
