---
title: "Provider Process Containment Phase 3 Execution Plan"
created: 2026-08-08
updated: 2026-08-08
tags: [runtime, runner, security, sandbox, filesystem, git, transfer, implementation]
---

# Phase Execution Plan

- Phase: `3 — Contained native file, Git, and transfer operations`
- Branch/base:
  `azents/runtime-containment-3-contained-operations` →
  `azents/runtime-containment-2-runner-backend`
- PR boundary: Move every remaining Agent-selected Runner filesystem, patch, Git,
  import, presentation, image-read, publication, and provider-delivery path access
  behind one bundled helper executed through the selected Phase 2 backend, without
  activating Provider containment or changing Control-facing operation/transfer
  contracts.
- Inputs:
  - Phase 2 commit `fb00c5a22` and PR `#1210`;
  - confirmed `runtime-260808/REQ`;
  - accepted `runtime-260808/ADR-D1` through `ADR-D10`;
  - approved `runtime-260808/DESIGN` revision 1 and authority IDs `M1` through
    `M12`;
  - Phase 2 `ExecutionSpec`, `ExecutionBackend`, `ExecutionProcess`, safe Agent
    environment, positive bwrap projection, and qualified backend lifecycle;
  - current Runner file, patch, Git, transfer, operation event, generation,
    cancellation, and integrity contracts.
- Deliverables:
  - one versioned Runner-local contained-operation protocol using bounded
    length-prefixed JSON control frames and separately bounded raw binary frames;
  - a Runner-side contained-operation client that starts the bundled helper through
    the already selected backend and owns framed request, event, response, binary
    streaming, cancellation, deadline, and complete-descendant cleanup;
  - a standalone bundled helper containing all Agent-selected file, text, list,
    search, stat, edit, patch, move, delete, bulk, Git ref/worktree/discovery,
    transfer snapshot, and transfer commit operating-system access;
  - exact read-only bwrap projection of only the bundled helper implementation and
    its contained patch kernel rather than the complete trusted Runner package or
    virtual environment;
  - all native Runner operation handlers delegated to the contained client while
    preserving existing operation payloads, body chunks, progress/final events,
    bounds, error codes, patch result shapes, and Git streamed output;
  - transfer downloads streamed from Control into a helper-owned same-directory
    stage and atomically committed only after verified completion;
  - transfer uploads snapshotted and read by the helper, with the trusted Runner
    transporting opaque bounded bytes and verifying the established manifest and
    generation/deadline fences;
  - direct v1 and bwrap backends using the same helper/client boundary, with no
    native trusted path exception or contained fallback;
  - Git credential helper behavior retained through the safe Agent environment and
    the Provider network namespace retained by the selected backend.
- Non-goals:
  - Docker or Kubernetes Provider security settings, temporary mounts, bootstrap
    wiring, capability advertisement, diagnostics, or real-provider E2E;
  - Worker readiness, prompt, status, API, frontend, OpenAPI/client, living Spec, or
    snapshot promotion changes;
  - changes to Runner Control operation envelopes, event payloads, transfer intent,
    cancellation/result values, transfer gRPC/protobuf, object storage, or Provider
    publication protocols;
  - a persistent Agent-accessible helper daemon, trusted filesystem allowlist,
    mirrored path authorization, Session filesystem isolation, new operation types,
    or performance-specific trusted bypass.
- Interfaces:
  - the protocol begins with an exact schema version and operation family; unknown,
    malformed, oversized, out-of-order, duplicate-terminal, or trailing frames fail
    closed with bounded helper/protocol categories;
  - JSON frames contain only typed metadata and bounded result values; file bodies,
    transfer chunks, patch bytes, and Git stream bytes use raw binary frames with
    the existing operation or transfer size limits;
  - helper stdout is protocol-only; Agent-visible stdout/stderr and Git output are
    typed event frames, while helper stderr is bounded internal diagnostic input and
    is never copied wholesale into logs or public errors;
  - the trusted Runner may perform lexical absolute/Workspace-relative path
    normalization but does not resolve symlinks, stat, open, read, write, list,
    search, mutate, or execute Git for an Agent-selected target;
  - the helper executes with the fixed safe Agent environment, the exact
    Runner-reported Workspace cwd, and the selected backend's filesystem/process
    projection; operation handlers never construct backend arguments or helper
    mounts;
  - one-shot native operations receive one request and one terminal response;
    streamed Git and transfer flows use ordered event/data frames and one terminal
    response without relying on stdin EOF;
  - cancellation, deadline, generation replacement, reconnect, and Runner shutdown
    terminate the complete helper descendant group through `ExecutionProcess`;
  - current patch parsing, preflight, staging, revalidation, atomic commit, exact
    failure reporting, and fault-injection contracts remain behaviorally unchanged
    after their filesystem kernel moves inside the helper;
  - the transfer manager retains admission, deduplication, tombstones, result
    delivery, integrity comparison, deadline, and generation authority but never
    opens the Agent-selected Runtime path.
- Approved Design mechanisms: `M3`, `M5`, `M7`
- Authority references:
  `runtime-260808/REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-10`,
  `REQ-14`; `runtime-260808/ADR-D3`, `ADR-D4`, `ADR-D6`, `ADR-D7`,
  `ADR-D8`, `ADR-D10`; `runtime-260808/DESIGN` revision 1; current
  `spec/domain/toolkit.md`, `spec/domain/workspace.md`,
  `spec/flow/agent-runtime-control.md`, `spec/flow/file-exchange-storage.md`, and
  `spec/flow/test-strategy-e2e-primary.md`.
- Design delta: `None`
- Removal obligations:
  - remove trusted Runner native file, edit, patch, list, search, stat, move,
    delete, bulk, and path-resolution authority for Agent-selected targets;
  - remove trusted Runner Git subprocess, worktree, repository discovery, branch,
    and process-group authority;
  - remove trusted Runner transfer opening, staging, snapshotting, reading,
    writing, and committing of Agent-selected Runtime paths;
  - remove the Runner filesystem or temporary view as a parallel Agent path
    authority while retaining Runner-owned lexical envelope validation and opaque
    byte transport.
- Absence verification:
  - function-level AST/static checks find no native filesystem kernel,
    `execute_apply_patch`, `create_subprocess_exec`, Git command construction, or
    direct PID/PGID signaling in native operation handlers;
  - `transfer.py` contains no Agent-path `os.open`, parent traversal, staging,
    snapshot, read, write, replace, link, unlink, or stat implementation;
  - all operating-system access for Agent-selected paths exists only in the exact
    bundled helper/contained patch files and is reached through `ExecutionBackend`;
  - shell/native parity tests prove the same allowed Workspace and `/tmp` paths and
    the same denial of Runner-private files, process identities, and sockets;
  - transfer tests prove the trusted Runner cannot publish or commit bytes without
    a successful helper terminal frame and verified manifest.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan | `/root` | `docs/azents/plans/runtime-260808-provider-process-containment-phase-3-contained-operations.md` | Phase 2 PR | Tracked Phase 3 scope and interfaces | Documentation validation, `git diff --check` |
| Framed protocol and Runner client | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/{contained_protocol,contained_client}.py`; focused tests | Phase 2 backend/process handle | Versioned bounded metadata/binary framing, one-shot and streaming client lifecycle | Ruff, ty, protocol malformed/oversize/order/cancel tests |
| Bundled helper and patch kernel | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/{contained_helper,contained_apply_patch}.py`; helper tests | Framed protocol | Standalone contained file/Git/transfer kernels with exact current semantics | Direct helper contract tests, patch suite, file/Git parity tests |
| Native operation integration | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py`; `tests/{operations,apply_patch}_test.py` | Client and helper | All file/Git operation handlers delegate through selected backend | Existing operation suite, streamed Git, cancellation, result compatibility |
| Transfer integration | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/{transfer,main}.py`; `tests/{transfer,main}_test.py` | Streaming helper client | Helper-owned download commit and upload snapshot/read with current coordinator contracts | Existing transfer suite, integrity, symlink, cancellation, shutdown, backpressure tests |
| Helper projection and image | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/containment.py`; `python/apps/azents-runtime-runner/Dockerfile`; containment/image tests | Exact helper file set | Read-only helper projection without Runner app/venv exposure | bwrap argv tests, image build, helper import/operation smoke, private-path canaries |
| Independent review | `/root/runtime-containment-reviewer` | Read-only complete Phase 3 diff | Stable implementation and validation | Requirements/security/protocol/path-authority/removal findings | Reviewer report or explicit no findings |

- Integration order:
  1. Commit this Phase 3 execution plan before implementation.
  2. Add the bounded frame codec and backend-neutral Runner client with synthetic
     helper process tests.
  3. Move current file and patch kernels into the standalone helper and prove exact
     result/failure compatibility in direct-backend tests.
  4. Move Git kernels and streamed output into the helper, then remove trusted Git
     subprocess and PID/PGID authority.
  5. Route every native operation handler through the client and remove the
     filesystem executor and native helper functions from `operations.py`.
  6. Move transfer path opening/staging/snapshot/commit into streaming helper modes,
     inject the selected backend into `RunnerTransferManager`, and preserve all
     coordinator/data-channel behavior.
  7. Positive-project only the exact helper files through bwrap and validate the
     production image helper path.
  8. Run complete Runner, patch, operation, Git, transfer, backend conformance,
     image, static removal, documentation, and scope-drift validation.
  9. Request independent review from `/root/runtime-containment-reviewer`, batch
     required corrections, run affected checks, and request targeted re-review only
     for material findings.
  10. Commit and open PR 3 against the Phase 2 branch before creating Phase 4.
- Independent review:
  - Reviewer: `/root/runtime-containment-reviewer`.
  - Scope: complete Phase 3 diff.
  - Criteria: no trusted Agent-path/Git/transfer access; exact positive helper
    projection; bounded non-confused framing; binary integrity; helper stdout/stderr
    separation; no fallback; backend neutrality; path/symlink safety inside
    containment; patch atomicity; Git credential/network behavior; transfer
    commit/snapshot integrity; cancellation/deadline/generation/shutdown cleanup;
    stable operation and transfer contracts; no Provider or Worker drift; completed
    removal obligations; `Design delta: None`.
  - Inputs: Requirements, accepted ADR, approved Design revision 1, multi-phase
    plan, Phase 2 contract and PR, this phase plan, current Specs, complete diff,
    static absence output, and validation evidence.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents-runtime-runner && uv run ruff format --check src tests`
  - `cd python/apps/azents-runtime-runner && uv run ruff check src tests`
  - `cd python/apps/azents-runtime-runner && uv run ty check --error-on-warning`
  - `cd python/apps/azents-runtime-runner && uv run pytest -q`
  - focused protocol, helper, patch, file, Git, transfer, cancellation, deadline,
    generation, reconnect, and shutdown suites
  - direct-backend helper smoke plus bwrap image helper and parity smoke
  - shell/native Workspace, `/tmp`, private-file, process, environment, and socket
    canaries
  - static/AST removal searches described above
  - documentation validation and `git diff --check`
- Scope-drift check:
  Confirm the diff implements only `M3`, `M5`, and `M7`. Remove Provider resource,
  security, temporary-volume, capability, readiness, prompt, API, frontend, E2E
  fixture, Spec promotion, or new Control/protobuf changes. Preserve current product
  behavior and omit any trusted path exception, persistent daemon, compatibility
  fallback, or Profile-authored helper/backend input.
- Context checkpoint:
  Record protocol version and bounds, helper file manifest and projection, migrated
  operation families, transfer streaming/commit semantics, preserved public
  contracts, completed removals and absence evidence, image/direct/bwrap validation,
  reviewer findings and corrections, branch/base/commit/PR, UID/GID 1000 Provider
  prerequisite, and exact Phase 4 Docker Provider inputs.
