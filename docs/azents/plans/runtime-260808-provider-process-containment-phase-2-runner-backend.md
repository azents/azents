---
title: "Provider Process Containment Phase 2 Execution Plan"
created: 2026-08-08
updated: 2026-08-08
tags: [runtime, runner, security, sandbox, implementation]
---

# Phase Execution Plan

- Phase: `2 — Runner backend, qualification, process, and environment`
- Branch/base:
  `azents/runtime-containment-2-runner-backend` →
  `azents/runtime-containment-1-contracts`
- PR boundary: Add the backend-neutral Runner execution boundary, initial bwrap
  adapter, pre-registration qualification, safe child environment, and process
  operation routing without changing native file/Git/transfer authority or Provider
  capability advertisement.
- Inputs:
  - completed Phase 1 commit `899e2ca88` and PR `#1209`;
  - confirmed `runtime-260808/REQ`;
  - accepted `runtime-260808/ADR-D1` through `ADR-D10`;
  - approved `runtime-260808/DESIGN` revision 1 and authority IDs `M1` through
    `M12`;
  - current Runner operation, cancellation, registration, image, and Runtime
    Control contracts.
- Deliverables:
  - one backend-neutral contained-execution specification and process-handle
    interface owned by the Runner;
  - explicit direct backend for retained v1 behavior;
  - initial bwrap adapter as the only owner of bwrap arguments, positive
    filesystem projection, PID/user namespace construction, and backend errors;
  - trusted `AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG` bootstrap schema version 1
    with deployment-selected backend, exact Agent Workspace path, Agent temporary
    backing path, Runner-private hidden paths, and bounded qualification timeout;
  - absent bootstrap selects the explicit direct backend; any present invalid,
    unknown, unavailable, or failed contained backend terminates startup without
    fallback;
  - deterministic contained qualification through the same backend start path
    before normal Runner Control client construction or registration;
  - code-owned child environment with required execution values and rejection of
    Runner-reserved names from operation input;
  - `bash` and managed-process start/write/wait/termination/shutdown routed through
    the backend-neutral process handle;
  - complete descendant termination retained across timeout, cancellation,
    Session termination, quota pruning, generation change, reconnect, and Runner
    shutdown;
  - Runner image includes the initial backend binary and deterministic package
    validation.
- Non-goals:
  - native file, patch, search, Git, worktree, import, presentation, image, or
    transfer helper containment;
  - Docker or Kubernetes Provider resource, mount, security, bootstrap wiring,
    capability advertisement, or startup diagnostics;
  - prompt, readiness, status, API, frontend, living Spec, or E2E promotion;
  - per-operation backend selection, Profile-authored backend arguments, backend
    fallback, or new durable qualification state.
- Interfaces:
  - the backend-neutral execution specification contains an argv command, absolute
    working directory, safe environment, standard-stream requirements, and bounded
    deadline/managed-process intent; operation handlers never construct backend
    arguments;
  - the process handle exposes backend-neutral wait, return code, stdin, stdout,
    stderr, complete-descendant termination, and close semantics rather than raw
    PID/PGID authority;
  - shell operations use the fixed `/bin/bash -lc <command>` command form through
    the selected backend;
  - the direct backend preserves uncontained v1 process behavior but still uses the
    code-owned safe environment;
  - contained bootstrap is trusted Provider/Runner configuration and contains no
    Profile-authored command-line arguments;
  - bwrap preserves the Provider network namespace, projects the exact absolute
    Agent Workspace read-write, maps the dedicated Agent temporary backing path to
    `/tmp`, preserves `/tmp/agent`, exposes the code-owned system toolchain
    manifest read-only, creates a fresh process view, drops capabilities, prevents
    privilege escalation and nested user namespaces, and excludes Runner-private
    paths and environment;
  - qualification completes before constructing the normal Control clients and
    `RunnerRegistration`; transport reconnect in the same Runner process reuses the
    already qualified backend;
  - current Runner operation envelopes and result/event contracts remain unchanged.
- Approved Design mechanisms: `M3`, `M4`, `M6`
- Authority references:
  `runtime-260808/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`,
  `REQ-9`, `REQ-10`, `REQ-11`, `REQ-12`, `REQ-14`;
  `runtime-260808/ADR-D2`, `ADR-D3`, `ADR-D6`, `ADR-D7`, `ADR-D10`;
  `runtime-260808/DESIGN` revision 1.
- Design delta: `None`
- Removal obligations:
  - remove direct Agent `create_subprocess_shell()` authority from Runner operation
    handlers;
  - remove Agent child environment construction through `os.environ.copy()`;
  - remove operation-handler PID/PGID signaling as the process lifecycle
    authority;
  - keep backend-specific command construction out of operation handlers.
- Absence verification:
  - static search finds no `create_subprocess*`, `os.environ.copy()`, direct
    PID/PGID signaling, or bwrap argument construction in the `bash` and managed
    process paths after integration; existing native Git subprocess authority
    remains explicitly assigned to Phase 3;
  - backend conformance tests prove direct and contained handles satisfy the same
    process lifecycle contract;
  - startup tests prove qualification precedes Control client construction and
    failure cannot register or fall back.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan | `/root` | `docs/azents/plans/runtime-260808-provider-process-containment-phase-2-runner-backend.md` | Phase 1 PR | Tracked execution scope | Snapshot/frontmatter validation, `git diff --check` |
| Backend contract and bootstrap | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/{containment,environment}.py`; focused tests | Fixed interfaces | Typed bootstrap, backend registry, safe environment, direct and bwrap adapters, qualification | Runner Ruff, format, ty, focused pytest |
| Runner startup integration | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`; `tests/main_test.py` | Backend contract | Pre-registration one-time qualification and bounded startup failure | Focused startup pytest, ty |
| Process operation integration | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py`; `tests/operations_test.py` | Backend process handle | Shell and managed-process routing with unchanged events and quotas | Focused process pytest, cancellation/timeout/shutdown tests |
| Runner image | `/root` | `python/apps/azents-runtime-runner/Dockerfile`; image validation only | bwrap adapter | Pinned image contains backend binary and required system tools | Docker build, binary/version probe, image smoke test |
| Independent review | `/root/runtime-containment-reviewer` | Read-only complete phase diff | Stable implementation and validation | Requirements/security/process-lifecycle/interface findings | Reviewer report or explicit no findings |

- Integration order:
  1. Commit this Phase 2 execution plan on the phase branch.
  2. Add typed bootstrap, safe environment, backend-neutral execution/process
     contracts, direct backend, and bwrap adapter with focused unit tests.
  3. Add deterministic qualification and integrate it before Control client and
     registration construction.
  4. Replace shell and managed-process direct subprocess/PID authority with the
     backend-neutral handle while preserving events, quotas, timeouts, and cleanup.
  5. Add the backend package and image validation.
  6. Run full Runner validation, startup/process regression tests, static removal
     checks, and scope-drift review.
  7. Request independent review from `/root/runtime-containment-reviewer`, correct
     required findings, and rerun affected checks.
  8. Commit and open PR 2 against the Phase 1 branch before creating Phase 3.
- Independent review:
  - Reviewer: `/root/runtime-containment-reviewer`.
  - Scope: complete Phase 2 diff.
  - Criteria: backend-neutrality, no Profile backend arguments, no contained
    fallback, pre-registration qualification, safe environment and secret
    exclusion, positive projection, privilege/process boundaries, descendant
    termination, v1 direct behavior, stable operation contracts, no native
    operation or Provider activation drift, and `Design delta: None`.
  - Inputs: Requirements, ADR, Design revision 1, multi-phase plan, this phase
    plan, Phase 1 contract, current Specs, diff, and validation evidence.
  - Output: grounded Critical/Warning findings or explicit no findings.
- Final validation:
  - `cd python/apps/azents-runtime-runner && uv run ruff format --check src tests`
  - `cd python/apps/azents-runtime-runner && uv run ruff check src tests`
  - `cd python/apps/azents-runtime-runner && uv run ty check --error-on-warning`
  - `cd python/apps/azents-runtime-runner && uv run pytest -q`
  - focused process cancellation, timeout, managed-process, environment,
    qualification, and startup tests
  - Runner image build plus backend binary/version and startup smoke probes
  - static removal searches described above
  - snapshot/frontmatter validation and `git diff --check`
- Scope-drift check:
  Confirm the diff implements only `M3`, `M4`, and `M6`. Remove native-operation
  helper containment, Provider resources or capability advertisement, prompt,
  readiness, persisted status, frontend, E2E fixture, or Spec promotion changes.
- Context checkpoint:
  - Bootstrap schema version 1 selects only the trusted `bwrap` adapter; absent
    bootstrap selects explicit direct v1 execution, while invalid, unavailable,
    failed, timed-out, or incompletely terminated containment fails closed with a
    bounded category and no fallback.
  - `ExecutionSpec`, `ExecutionBackend`, and `ExecutionProcess` own process start,
    streams, state, complete-descendant termination, and shutdown without exposing
    PID/PGID authority to shell or managed-process handlers.
  - Qualification runs before registration and Control client construction, checks
    parent and descendant authority, and proves complete-descendant termination with
    a contained grandchild Workspace-lock canary.
  - Agent children receive only the code-owned safe environment; Runner variables
    are absent and reserved operation overrides are rejected.
  - The Runner image contains bubblewrap 0.11.0 and util-linux 2.41. Image digest
    `sha256:ef4e057c7dbee8d4b80de16dbf52081a830c8d9ae06386b3a8d73927510c25b2`
    passed binary/option probes and the strengthened adapter diagnostic.
  - The diagnostic root/privileged execution is not Provider deployment
    conformance. Docker and Kubernetes capability advertisement remains blocked
    until Phase 4 and Phase 5 qualify the real Runner with preserved UID/GID 1000;
    changing to root, privileged, setuid, or another material mechanism requires
    renewed Design authority.
  - Runner Ruff format/check, whole-project ty, all 178 tests, focused startup,
    environment, cancellation, timeout, quota, generation, and shutdown coverage,
    documentation validation, static removal searches, and `git diff --check`
    passed.
  - `/root/runtime-containment-reviewer` completed the full review and two targeted
    re-reviews; all grounded warnings were corrected and the final result had no
    remaining Critical or Warning findings.
  - Branch/base is `azents/runtime-containment-2-runner-backend` on
    `azents/runtime-containment-1-contracts`. Phase 3 receives the selected backend,
    safe execution specification, process handle, positive projection, and native
    Git/file/transfer helper boundaries without Provider activation.
