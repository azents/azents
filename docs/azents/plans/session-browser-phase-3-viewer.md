---
title: "Session Browser Phase 3 Execution Plan"
created: 2026-10-15
tags: [browser, session, runtime, frontend, implementation, security]
document_role: supporting
document_type: supporting-plan
---

# Phase Execution Plan

- Phase: 3/4 — authenticated Browser admission, shared logical stream consumer and Session supporting panel.
- Branch/base: `feat/session-browser-261015-viewer` → `feat/session-browser-261015-runner` at `ce90515b7` (PR #2263).
- PR boundary: reachable current-Session Browser projection/closure/attachment, Browser-domain shared transport routing and Runner-owned live consumer, source-generated public clients, accessible desktop/mobile supporting-panel UI and required scoped tests.
- Inputs: [approved Design revision 2](../design/browsercmd-261014-session-browser.md), [Requirements](../requirements/browsercmd-261014-session-browser.md), [ADR](../adr/browsercmd-261014-session-browser.md), phase 1 strict transport authority (PR #2262) and phase 2 Runner/Engine commands (PR #2263), current Session resource access, Authentication and Runtime Control Specs.
- Deliverables: authorized users inspect/select exact current task/page and observe live bounded frames; directing users send scoped input/dialog responses or close the selected page; observation-only participants have no input path. Dismiss/disconnect closes attachment and actual held interactions, not browser tasks, profile state or Agent work. Stale/closed deep links remain explicit rather than selecting another page.
- Non-goals: merge/deployment, new Runtime ports/raw CDP/MCP or arbitrary JS dispatch, persistent human control/help/ownership workflows, new durable grants/ticket tables, native profile management, viewer-driven remote viewport resize, image/input history, uncertain input replay, managed Skill and final full-feature acceptance/spec promotion (phase 4).
- Approved Design mechanisms: M1/M2/M3/M9/M10/M12/M13/M16, using completed M4/M5/M11/M15/M17 boundaries unchanged.
- Authority references: browsercmd-261014/REQ-1/2/4/5/6/8/9/12; ADR-D2 and unchanged prior Browser transport/resource/admission authorities; Design M1-M17; current Session authorization and common transport contracts.
- Design delta: None.

## Fixed integration contracts

### Public domain and current authority

Use a Browser public domain under normal authenticated Session resource routes. A resource identifies workspace handle, agent and concrete Session; requested task/page/incarnation only selects a resource after authorization. List/projection and attachment require existing observation access; closure/input additionally require directing access. Public subagent read targets do not become writable. No page title/content before authorization, no scheduling owner/root alias used as browser ownership.

REST projection returns availability, content-free reason, current task/page projections and input permission. Page closure accepts the exact current target. The public WS attaches that target after normal identity authentication and live resource admission. Reuse the existing identity-only `create_ws_ticket`/`verify_ws_ticket` primitive (30-second HMAC of user/authentication Session) used by Chat; do not create Browser or Terminal ticket persistence/grants. Recheck live account/authentication Session plus concrete resource access before exposing content and during attachment; Origin is only CSWSH validation, never identity. Strip credential query data from generic logging context.

Construct `BrowserStreamAuthority` server-side with common current Runtime/desired/Runner generation, owner fingerprint, user/authentication Session, agent and admitted concrete Session/task/page/incarnation/input scope. Browser service routes supply common transport targets without Web service/revision/exposure/port admission or quotas. Keep Web-only authorities and loopback consumers isolated. Reuse current Runtime command binding for bounded list/projection; no Runtime auto-start simply to inspect an unavailable resource.

### Runner and application messages

Keep the common envelope/flow-control/owner session transport authoritative. Add a distinct Runner-owned Browser consumer beneath shared dispatcher/accounting, not a loopback listener. Shared Browser application DTOs/codecs live in runtime-control and reject malformed primitives, unknown fields, unsupported combinations and oversized messages at ingress. The Runner owner freezes the precise shared codec shape with root/API/UI before callers implement it.

Runner-to-viewer messages carry typed current status/dialog, bounded frame metadata/image bytes, and input acknowledgements. Viewer-to-Runner messages carry current attachment, admitted target, source-frame/dimensions and strictly increasing input sequence with a closed pointer/wheel/key/composition/dialog action set. Public page closure may use REST; it shares the same current manager lifecycle. ACK means accepted/dispatched browser input, not site success.

A page-shared latest-frame slot owns bounded volatile viewport captures, with at most the latest bytes rather than historical frames. Completed WS messages stay within the existing 1 MiB bound and use at most 256 KiB common fragments; metadata and source pixels are bounded. No frame goes through intentional PNG capture/file/model publication. Source viewport remains fixed; panel size only changes presentation. Capture failure affects the Browser resource/attachment, not independent Web/Terminal/file service.

Keep only bounded current/acknowledged metadata per attachment. Source-frame admission combines current resource incarnation, attachment/input sequence, acknowledged viewport and current navigation/resource evidence; do not reject every valid input merely because a newer periodic capture arrived, and do not admit old coordinates after navigation/replacement. No old attachment/input is replayed on reconnect.

Resolve stream targets from the manager's already trusted task/Session registry, including its bound working directory; the viewer cannot supply that directory or allocate another profile by attaching. Revalidate final current generations/target before effects. `allow_input=False` rejects input/dialog/closure before guard acquisition or SDK effects.

Pointer gestures, held keys and IME start/commit/cancel are actual transient interactions sharing the phase 2 task guard. Preserve one actor across a continuous interaction, commit composition once, and clean only that actor's pressed state on end/cancel/disconnect. Dialog responses reuse the exact current identity and repeated original-operation handoff. A passive viewer holds no input grant.

### UI and generated clients

Browser is a destination in the existing Session supporting panel, not a new Workspace tab/page shell. Add a container/component/Page feature with discriminated view states and generated REST client calls through the existing BFF/tRPC boundary. Shared WS metadata/input codecs are strictly narrowed at the UI boundary. Generated outputs remain root-owned and source-generated.

Use distinct Browser task/page/incarnation link keys rather than scheduled-task `taskId`. An incomplete/stale/closed tuple does not silently pick another task. Links retain the current concrete Session route and never grant authority. Unmount or explicitly deactivate the attachment when the panel is dismissed/another destination is selected, even if the desktop shell remains mounted. Provide exact tool-result/task linkage through the existing Session panel flow without a new Engine authority contract.

Keep image preview dominant, task/page controls nearby and safe source/title/status readable. Connected/stale/unavailable/read-only/actual-conflict/dialog states, keyboard focus, pointer cancellation and mobile containment are explicit. Transform displayed coordinates against acknowledged source dimensions and reject letterbox/outside/stale positions. Read-only UI supplies no input handlers/sends. Blob/image resources are released on replacement/unmount; no image history. Do not reuse Terminal pending-input replay semantics.

## Workstreams and ownership

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared Browser viewer DTO/codec and Runner domain consumer | `/root/browser-runtime-research` (implementation follow-up after plan) | New runtime-control Browser viewer contracts/tests; Runner Browser consumer/live capture/input modules/tests; narrow browser.py, web_session_dispatcher.py, main.py integration and related Runner tests | Phase 2 registry/guard, phase 1 authority/flow control; fixed public interface | Current typed Browser stream, page-shared latest-frame capture, input/IME/gesture/dialog cleanup, strict domain dispatch | Full library/Runner quality/type/tests, actual SDK stream fixtures, stale/read-only/conflict/backpressure/disconnect tests |
| Browser public admission/service/current routing | `/root/browser-access-transport-research` (implementation follow-up after plan) | New backend api/public/browser and services/runtime_browser; narrow core/deps, API mounting, runtime common routing/authority/pool/policy integration and tests | Shared DTO handshake; current auth/Session/Runtime routing | Authorized projection/page close/WS attach with existing identity ticket, common transport to Browser authority, live revocation | API/service/domain-boundary/current-generation/auth/revocation/owner tests; backend whole typecheck and focused tests |
| Session Browser supporting-panel UI | `/root/browser-viewer-implementation` | New features/session-browser; chat panel view/state/link/refresh/container components/tests; trpc browser router/_app registration; locale Browser copy and colocated stories | Public API projection/close/WS contract and root-generated public client; shared strict viewer codec | Real desktop/mobile pane and scoped keyboard/pointer/IME/status/link flow | Format/lint/typecheck, pure wire/input/route tests, static real-component stories/play checks; product visual QA |
| Root integration, clients, specs, environment and acceptance preparation | `/root` | docs/plans/Specs; generated OpenAPI/Python/TypeScript clients; integration conflict resolution; Session-owned devenv/evidence; scoped product E2E prerequisite wiring as needed | All owners | Stable root-integrated phase and exact authority/drift review, verified image/public UI paths, PR | Root-owned complete touched-package checks, built product-image probe, authenticated normal API/stream/browser UI checks, docs/diff checks |

Owners read current applicable AGENTS/conventions and stay within their paths. Shared contracts are frozen before API/UI consumers; coordinate interfaces via root. Neither owner commits/pushes, generates clients, starts review or broadens authority. Root resolves shared-path conflicts. Research roles are explicitly reused for bounded implementation because their current code/authority context is relevant; the single reviewer remains `/root/browser-feature-reviewer`.

## Removal and absence verification

No additional obsolete product behavior is authorized for removal. Preserve existing Web/Terminal/file/Session policy and native profile bytes. Replace Web-only assumptions only where the common dispatcher/routing now needs a closed Browser domain branch; keep Web service admission/port/exposure in Web-only adapters. Verify wrong-domain/no-loopback/no-service-capacity effects, no extra ingress/debug listener, no persistent human-control/help registry, no Browser grant table, no capture/input transcript, no replay and no native profile deletion/copy.

## Integration, validation and checkpoints

1. Root records this plan and reports the complete phase boundary; owners confirm scopes and exact shared application/public DTOs.
2. Shared strict viewer contracts and Runner owned consumer; backend admission/current routing; UI starts against frozen public/shared shape and generated client after root regeneration.
3. Root integrates all owners and runs runtime-control/Runner full Ruff/format/typecheck/pytest, backend whole typecheck/modified Ruff/format and complete affected auth/API/service/routing/Engine regressions; TypeScript format/lint/typecheck/pure tests and web/Storybook build.
4. Root rebuilds the product Runner image and uses fresh synthetic state. Validate real admitted authenticated Browser transport, account/Session/read-only/revocation fences, actual viewer images/coordinates/IME/gestures/dialog/closure/dismissal/reconnect and existing Web regression within this phase's capabilities. Record actual limitations instead of substituting mocked/focused results for product acceptance.
5. Root freezes complete integrated diff and requests read-only phase review from the same reviewer. Root fixes material findings and reruns affected validation; targeted re-review only after stable corrections. Commit/open phase 3 PR before phase 4.
6. Phase 4 remains responsible for managed release Skill, actual Engine/model/original publication combined E2E, full acceptance matrix, final spec promotion and plan cleanup. Requirements/Design implementation dates remain unset until complete verification.

- Scope-drift check: M1/M2/M3/M9/M10/M12/M13/M16 behaviors covered within existing authority; no new persistence/control/configuration/permission/relay/replay mechanism. New material decisions return to feature design before edits.
- Initial checkpoint: phase 2 PR #2263 opened at ce90515b7 after five review fixes, root shared374/Runner452/backend310 checks and 15 product-image assertions. Same reviewer targeted re-review passed 33 tests/no material findings. Phase 1 #2262 CI success remains unmerged. Phase 2 CI is running; Runner host/browser job already passed. Existing Session devenv ID060d7f0bf5ce4a49 and data root remain preserved; neither prototype state nor credentials are acceptance fixtures.
- Blocking prerequisites: exact shared application/public field contract handoff, generated clients, normal authenticated Session access in the preserved devenv, built Runner image with phase 3 consumer. The existing persistent Gateway-to-Control source uses a Gateway-only mTLS identity; backend discovery must establish an already authorized API/common-transport connection path before activation. Reusing Gateway credentials opportunistically or adding a new port/role/configuration is not authorized by this plan. Decision-independent Runner/UI contracts may proceed; any genuinely new material transport authority returns to the ADR/approval workflow. No merge/deployment authorization.
