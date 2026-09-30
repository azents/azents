---
title: "Direct File Transfer Phase 4 Runtime Outbound"
created: 2026-09-29
tags: [files, runtime, implementation, phase-plan]
---

# Direct File Transfer Phase 4 Runtime Outbound

## Phase Execution Plan

- Phase: `4/7 — verified direct PUT for Runtime outbound consumers`
- Branch/base: `azents/files-260929-4-runtime-outbound` → `azents/files-260929-3-runtime-get` (PR #1958).
- PR boundary: `Switch present_file, Runtime channel_action attachments, read_image, and Workspace download preparation to exact-attempt Runner PUT and trusted immutable verification; preserve their existing publication, consumption and provider semantics.`
- Inputs: [files-260929/REQ](../requirements/files-260929-direct-file-transfer.md), [files-260929/ADR](../adr/files-260929-direct-file-transfer.md), [files-260929/DESIGN](../design/files-260929-direct-file-transfer.md) approved revision 1 / M1–M8; reviewed Phase 2 PUT protocol, immutable promotion, cleanup and storage-egress prerequisites; reviewed Phase 3 source transport and exact result settlement.
- Deliverables: `All listed upload consumers admit DIRECT_OBJECT upload transport. Runner snapshots and hashes the bounded regular source, obtains an authenticated exact-attempt PUT ticket and publishes only the trusted immutable verified result. Consumer claims retain feature-owned Exchange publication, provider-native delivery, normalized ModelFile creation, or response-scoped Workspace streaming. Generic Worker 8 MiB transfer rejection is removed for these consumers; read_image remains bounded to 20 MiB and external policies remain authoritative.`
- Non-goals: `No Chat browser PUT, browser GET redirect, public/admin policy cutover, new durable file identity, provider/admin limit increase, legacy byte-stream fallback, long-lived Runner storage credentials, or live infrastructure mutation.`
- Interfaces: `RuntimeToServerTransferService.prepare_consumer/transfer; RuntimeToProviderBatchService admission/verified consumption; existing CoordinatorUploadTransport and exact PUT claim/renew/complete; Worker service policy composition; WorkspaceDownload consumer lifetime and feature publication callbacks.`
- Approved Design mechanisms: `M1` as direct-path eligibility, `M3`, `M6`, `M7`, `M8`.
- Authority references: `files-260929/REQ-1`–`REQ-5`, `files-260929/ADR-D1`, `ADR-D3`, `ADR-D5`, `ADR-D6`, approved `files-260929/DESIGN`, current Agent Runtime Control, File Exchange Storage, Workspace and External Channel Specs.
- Design delta: `None`.
- Removal obligations: `Remove Runner-to-Control UploadTransfer body-stream usage for all listed consumers and their unrelated generic 8 MiB Worker gate. Keep later-phase Workspace browser body streaming until the approved Phase 6 redirect/lifetime replacement. Retain still-authorized control-stream protocol only where not yet removed; direct attempts cannot invoke it.`
- Absence verification: `Audit all RuntimeToServer/RuntimeToProvider consumers, assert DIRECT_OBJECT at admission and dispatched intent, exercise exact direct PUT with no UploadTransfer body frames, and retain failure/cleanup tests. Search Worker composition for the old generic 8 MiB gate without removing independent 20 MiB image or external provider/admin/action-aggregate checks.`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Direct upload consumer admission | `/root` | `python/apps/azents/src/azents/runtime/transfer/{runtime_to_server,runtime_to_provider}*` | Phase 2 PUT contract | Explicit direct-only upload admission across all approved outbound consumers | Consumer lifecycle/partial batch/recovery tests and transport assertions |
| Feature policy composition | `/root` | `python/apps/azents/src/azents/worker/deps*`, `runtime/transfer/{runtime_image_read,present_file_publication,workspace_download}*` and relevant feature tests | Direct admission | 128 MiB eligible generic transfer; retained 20 MiB image and external native/admin aggregate bounds | Boundary/composition tests and feature authorization/publication regressions |
| Exact PUT verification | `/root` | Existing Runtime transfer gRPC/stores, runtime-control and Runner tests; E2E fixture only as needed | Consumer admission | Current-generation exact verified immutable PUT, successful consumer acknowledgement and cleanup, no relay | Root-run affected suites, actual Runner/RustFS consumer E2E and absent-relay checks |
| Integrated validation and review | `/root` | Phase-owned paths and this plan | All workstreams | Stable phase diff, measured gates, authority/absence evidence and independent review | Root full Ruff/format/ty/pytest, generated drift/diff checks, read-only assigned review |

- Integration order: `Audit current feature consumers and policies → select direct upload admission → separate Worker generic/image/provider policies → prove feature publication and consumer lifetime → integrated root validation → independent review → commit/stacked PR.`
- Independent review: `/root/files-260929-reviewer` performs one read-only review of the stable complete phase diff; only root requests review after integration and validation.
- Final validation: `Root runs backend, runtime-control and Runner Ruff/format/ty/full tests; exact upload claim/renew/complete and Memory/Redis contract regressions; consumer/provider publication and cleanup cases; actual Runner/RustFS outbound feature E2E; git diff --check and pre-commit. Record restrictive-network deployment evidence separately from unit/isolated fixture evidence; no live cluster write is authorized.`
- Scope-drift check: `Only approved M1/M3/M6/M7/M8. Preserve existing source/consumer ownership, Session authority, provider outcome recovery, cancellation, deadlines and stable failure behavior. Phase 5 owns Chat; Phase 6 owns browser redirects and coordinated common/Admin policy migration; Phase 7 owns full integrated deployment matrix and Spec promotion.`
- Context checkpoint: `Record direct admission and consumer map, policy values and retained checks, exact immutable verification and no-relay evidence, tests/E2E prerequisites, review findings, risks and remaining rollout gates. Preserve the same assigned reviewer and all prior PR bases.`

## Execution Checkpoint

- Central Runtime-to-server admission now selects direct PUT for `present_file`, `read_image`, and both Workspace download adapters. Runtime-to-provider batch admission selects direct PUT for every Runtime source. The immutable verified object, exact consumer acknowledgement, Exchange publication, ModelFile normalization, provider completion recovery, and response-scoped Workspace EOF settlement remain unchanged.
- Worker generic Runtime transfer capacity is 128 MiB; `read_image` remains 20 MiB. External Channel native/admin per-file and action-aggregate preflight remain in `file_transfer.py`. Removed the generic provider batch's accidental use of a per-file bound as an action total. Tests admit two metadata-only 128 MiB sources independently and reject either product/provider per-file oversize before any Runtime admission; they do not claim to transfer two real large file bodies.
- Root final backend Ruff/format/ty pass; full pytest `6017 passed, 3 skipped`. Runtime Control Ruff/format/ty pass and full pytest `227 passed`; Runner Ruff/format/ty pass and full pytest `295 passed`. Initial feature-focused tests `45 passed`; all later per-file/aggregate regressions are included in the final full run. `git diff --check` passes.
- Actual Runner/RustFS product E2E `test_workspace_upload_direct_put_finalize_and_exact_download` passed (`1 passed`, 47.91 seconds): browser-style PUT/finalize, committed Runtime bytes, direct Runner PUT for Workspace preparation, and exact downloaded body. This proves the existing small-file consumer journey, not 128 MiB across every provider/network mode. Runner regression `test_direct_upload_puts_snapshot_without_control_byte_relay` verifies zero legacy upload calls, and the direct-only server rejects `UploadTransfer`.
- Workspace browser policy remains 64 MiB and its response-scoped HTTP body consumer is retained until Phase 6; Phase 5 owns Chat and Phase 6 owns common/Admin policy migration. Phase 7 retains the broader provider/browser/large-file and restrictive-network deployment matrix and Spec promotion.
- Independent read-only review by `/root/files-260929-reviewer` approved the stable complete phase diff after the root final validation, with no correctness, security, data-integrity or material convention findings. Verified direct-only caller coverage, per-file versus action-total policy ownership, retained feature fencing, unchanged verified consumer lifecycle, and the explicit Phase 6/7 rollout boundaries.
