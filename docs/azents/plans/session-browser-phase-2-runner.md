---
title: "Session Browser Phase 2 Execution Plan"
created: 2026-10-15
tags: [browser, runtime, engine, implementation]
document_role: supporting
document_type: supporting-plan
---

# Phase Execution Plan

- Phase: 2/4 — Runner browser resources, commands and Engine tools.
- Branch/base: `feat/session-browser-261015-runner` → `feat/session-browser-261015-transport` at 3333fa404. Phase 1 PR: https://github.com/azents/azents/pull/2262.
- PR boundary: product-provisioned browser SDK/engine; Runner-owned native Session contexts, live task/page/frame/ref/dialog registry; typed command execution; current-input arbitration; DOM/glance/capture/file operations; Engine open/observe/act with real model image materialization. No Browser public viewer routes or UI until phase 3.
- Inputs: [approved Design revision 2](../design/browsercmd-261014-session-browser.md), [Requirements](../requirements/browsercmd-261014-session-browser.md), [ADR](../adr/browsercmd-261014-session-browser.md), phase 1's explicit shared transport contract.
- Deliverables: usable Agent browser tool contract against product Runner commands, isolated native state and explicit current targets, observed result/error/uncertainty, retained original captures, and no MCP/control-mode/Agent installation reliance.
- Non-goals: public Browser API/viewer, managed Skill content (phase 4), arbitrary Agent JS/SDK programs, profile backup/reset/retention, configuration/version registry, privileged infrastructure changes or deployment.
- Approved Design mechanisms: M4-M12, M15, M17; current Session authority M2; later common viewer uses these same resources.
- Authority references: current ADR-D1/2/4, preserved prior resource/admission decisions, REQ-2 through REQ-12 and REQ-14, existing Runtime/image/file/Session Specs.
- Design delta: None.

## Fixed integration contracts

Shared Python browser command/result DTOs and JSON-ingress codecs live in azents-runtime-control (a library), usable by backend and Runner. Backend apps never import Runner app code. Operation names are `browser.open`, `browser.observe`, `browser.act`, plus a bounded status/list operation needed by the later authorized viewer. These names are internal, not extra model tools. Responses carry current task/page/frame/ref/incarnation and bounded projection/capture metadata, not browser byte streams.

Command authority explicitly carries concrete execution Session and current working-folder binding separately from operation scheduling owner. Root/model cannot submit another Session via tool input. Runner validates transport generation and task/page/ref binding immediately before effects. Browser profile paths derive current Runner Workspace evidence plus trusted Session association; no fixed server HOME or prototype input.

Open/observe/act arguments use one top-level provider-compatible object. Typed actions/observations are validated at ingress. No generic JS dispatcher. Upload paths remain authorized Runtime files; original capture/download paths use current Session context. Native Session contexts reuse state naturally; page/task handles do not survive resource replacement.

Actual task interaction guard is shared with future viewer input and handles current collisions/composition/gestures, with no persistent human ownership/control mode. Event subscription precedes its triggering action. Dialog responses must be possible without operation-wide deadlock. Unknown dispatched result/cancellation is not replayed. Original PNG is not overwritten by ModelFile preparation.

Support-dependent sandbox initialization recognizes specific native incompatibility, not generic launch errors. Product SDK and engine are locked/image installed; preserve trusted Runtime proxy/network policy and do not enlarge privileges. Controlled synthetic local sites only for tests.

## Workstreams and ownership

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared DTO/codec and Runner manager/commands/provisioning | `/root/browser-runner-implementation` | New runtime-control browser contract modules/tests; Runner browser modules, operations/main/typed payload hooks, tests, pyproject/lock/Dockerfile | Approved contracts; existing Runner scheduling | Complete typed SDK implementation and command results, profile/task/ref/event/capture/current-input and sandbox behavior | Shared DTO + Runner quality/type/unit and live synthetic SDK tests, no skipping required fixture |
| Backend command client and Engine tools | `/root/browser-engine-implementation` | New backend runtime browser client/typed integration; engine/tools/browser modules/tests, runtime I/O/adapter/RuntimeToolkit binding only as needed | Shared DTO contract from Runner owner | Three model-facing tools, trusted concrete authority, actual image FilePart and cancellation/error mapping | Source/schema/tool/error/model-image tests and backend quality/type checks |
| Integration/validation/spec/prerequisites | `/root` | docs/plans/Specs; Session devenv and evidence; any necessary shared wiring conflict resolution | Both bounded workstreams | Stable integrated phase, exact authority/drift checks, complete reviewer input | Root-owned package checks, real Runner fixture, image/provisioning/current policy and cancellation evidence |

Root arbitrates interface changes. Implementers coordinate exact DTO shape before editing caller/handler wiring, report concrete checkpoints and do not edit each other's paths. Only root requests independent review from `/root/browser-feature-reviewer`; neither implementation agent commits/pushes. If a new material mechanism is required, report it rather than implement it.

## Removal and verification

- Replace system-only/unpinned alleged browser provisioning with uv-managed locked SDK and matching image engine. Verify actual Runner environment import/launch and supported architectures/build command; no user installation fallback.
- Remove none of existing Session native bytes or Web/Terminal/file semantics. No profile copy/delete, global close cleanup, help registry/MCP/JS compatibility path. Verify scoped shutdown and commands after resource replacement.
- Shared definitions live only in the library; exhaustive typed command/result decode and Runtime operation failure translation. Search old dummy/ref/raw JSON dispatch or direct app imports.

## Integration and final validation

1. Shared DTO/codec freeze and owner handoff to Engine lane.
2. Runner native state/task identity + provisioning/current proxy/sandbox; observation/ref/event/file/dialog/real conflict/cancel behavior.
3. Engine binding/current authority and actual image ModelFile path with error propagation.
4. Root stable integration: full runtime-control/Runner pytest, ruff, format, ty; backend whole-project ty and focused Engine/runtime/ModelFile tests; product Runner image live synthetic tests and same-Session state/cancellation, SDK/Chromium/network evidence; docs/diff/scope checks.
5. One read-only independent review of complete stable phase, root corrections and invalidated-check reruns; commit/PR to phase 1 before phase 3.

Capture evidence by exact head/image/environment and bounded outcome, never tokens/full page/input/cookies. Existing Session devenv ID060d7f0bf5ce4a49 is ready at the phase1 code root; product image currently phase1 must be rebuilt for actual browser implementation. UI route currently login-only observed, Browser product E2E not yet possible and not claimed complete.

- Scope-drift check: every approved category has implementation/test ownership; no new persistence/control/permission/config/relay mode; later-phase API/UI/Skill excluded.
- Context checkpoint: phase2 starts after phase1 stable review and PR2262; no phase2 implementation completed yet. CI for the stack remains root-owned and running; no merge authorization.
