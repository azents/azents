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
- Inputs: [approved Design revision 3](../design/browsercmd-261014-session-browser.md), [Requirements](../requirements/browsercmd-261014-session-browser.md), [ADR](../adr/browsercmd-261014-session-browser.md), phase 1 strict transport authority (PR #2262) and phase 2 Runner/Engine commands (PR #2263), current Session resource access, Authentication and Runtime Control Specs.
- Deliverables: authorized users inspect/select exact current task/page and observe live bounded frames; directing users send scoped input/dialog responses or close the selected page; observation-only participants have no input path. Dismiss/disconnect closes attachment and actual held interactions, not browser tasks, profile state or Agent work. Stale/closed deep links remain explicit rather than selecting another page.
- Non-goals: merge/deployment, new Runtime ports/raw CDP/MCP or arbitrary JS dispatch, persistent human control/help/ownership workflows, new durable grants/ticket tables, native profile management, viewer-driven remote viewport resize, image/input history, uncertain input replay, managed Skill and final full-feature acceptance/spec promotion (phase 4).
- Approved Design mechanisms: M1/M2/M3/M9/M10/M12/M13/M16/M18, using completed M4/M5/M11/M15/M17 boundaries unchanged.
- Authority references: browsercmd-261014/REQ-1/2/4/5/6/8/9/12; ADR-D2 and unchanged prior Browser transport/resource/admission authorities; Design M1-M17; current Session authorization and common transport contracts.
- Baseline independent-lane Design delta: None; those revision 2 mechanisms and completed evidence remain preserved.
- Source baseline: ADR-D5 option A accepted at 10:22 KST; complete disclosed Design revision 3/M1-M18 authorized by the requester's immediate implementation instruction at 10:53 KST on 2026-10-15. Same reviewer authority/feasibility audit passed. Design delta: None against approved revision 3. Start the source lane immediately without repeating this approval.

## ADR-D5 Decision and Revised Approval Gate

The requester selected the API-owned Browser-purpose source on existing ordinary Control TLS. New Design M18 explicitly binds one attachment/open to a fresh Control connection challenge and purpose-separated `azents-api` proof, rather than assuming source IDs globally consume bearer tokens. Initial proof/setup deadlines are separate from bounded live transport/auth-Session expiry. Current access/input checks, local/deployed same-RPC parity, disabled common-plane response, strict domain/capacity/fingerprint/Owner cleanup and no replay are fixed in the draft. No source implementation, new port/table/key distribution or Gateway/transfer credential reuse has occurred.

Root recorded accepted ADR-D5 and revised the primary Design to revision 3. The same exact reviewer `/root/browser-feature-reviewer` completed a read-only full Requirements/ADR/Design/current-source authority/feasibility audit on 2026-10-15: passed, no blocking authority/security/lifetime contradiction or required material change. Source-grounded feasible with implementation/delivery evidence conditional. That audit is not the mandatory complete phase 3 code review, which remains after actual source implementation and root integration. Requirements remain unchanged. The requester instructed immediate implementation of the disclosed revision 3/M1-M18 scope at 10:53 KST; that instruction replaces the redundant approval wait.

## Fixed integration contracts

### M18 source execution decomposition

The disclosed revision 3 scope is authorized. Source/protocol owner implements the Browser-only API role, dedicated ordinary-Control RPC, fresh connection challenge and one exact signed Hello/profile/OPEN, separate Browser-purpose key/audience for `azents-api`, broker/Owner/current-access/domain/capacity/cleanup. Public API owner implements first-attach identity ticket/current target admission, current auth-Session expiry, one-attachment source lifecycle on existing endpoint/TLS, input and live access revalidation. UI owner implements the normal API socket/first attach, strict status/binary/ACK decoding, one live Blob URL, current target/nav/source fencing, image-load ACK, input sequence and unknown-outcome non-replay.

Freeze the exact bootstrap/client/current-scope validator interfaces among owners before callers edit. Shared signing/client/protocol belongs to the source owner; `runtime/deps.py`, Browser API/service/repository and its shared current-scope validator belong to the API owner. Source owner wires that validator into Control without editing the API-owned implementation. No concurrent overlapping edits, generated manual changes, new port/table/secret distribution/configuration mode, transfer/Gateway identity reuse or legacy role fallback. Root integrates and owns regeneration, stable validation, the single full-phase review and PR.

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
| Browser public admission/WS/current scope | `/root/browser-engine-implementation` | Backend api/public/browser and services/runtime_browser; current repository authority/expiry reader; runtime/deps.py source client lifecycle; shared current-scope validator for Control; related tests | Frozen source client/proof contract; existing normal user ticket/Session/Runtime binding | Existing REST plus real first-attach authenticated WS, source authority/deadlines, pre-input/live access and safe cleanup | API/service/current-generation/auth/read-only/revocation/socket tests; backend whole typecheck and focused tests |
| API Browser source/protocol/Control routing | `/root/browser-access-transport-research` (implementation role) | proto/runtime_stream_session and generated shared outputs; runtime-control source client/role/codec; new core Browser credential module; Control source RPC/registration; common broker/Owner/relay/domain validation and tests; no API-owned service/repository/runtime-deps edits | Approved revision 3/M18; API-owned current-scope callback contract | Challenge-bound one-OPEN API Browser source on existing ordinary listener, strict domain/proof/lifetime/Owner/capacity, Web boundaries unchanged | Shared protocol/client and credential/Control/broker/relay/current-scope tests; full relevant quality and type checks |
| Session Browser supporting-panel UI | `/root` (primary ownership after the requester's 2026-10-15 correction; prior implementation handed off) | New features/session-browser; chat panel view/state/link/refresh/container components/tests; trpc browser router/_app registration; locale Browser copy and colocated stories | Public API projection/close/WS contract and root-generated public client; shared strict viewer codec | Real desktop/mobile pane and scoped keyboard/pointer/IME/status/link flow | Format/lint/typecheck, pure wire/input/route tests, static real-component stories/play checks; product visual QA |
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
- Initial checkpoint: phase 2 PR #2263 opened at ce90515b7 after five review fixes, root shared374/Runner452/backend310 checks and 15 product-image assertions. Same reviewer targeted re-review passed 33 tests/no material findings. Phase 1 #2262 CI success remains unmerged. Phase 2 CI workflow 38659051553 completed successfully with 35 successful jobs, including four required E2E shards and Web E2E; PR remains OPEN/CLEAN and unmerged. Existing Session devenv ID060d7f0bf5ce4a49 and data root remain preserved; neither prototype state nor credentials are acceptance fixtures.
- Blocking prerequisites: shared application/public field handoff, generated clients, normal authenticated Session access in the preserved devenv, built Runner image with phase 3 consumer. Discovery confirmed that production Public API has no authorized common-stream source: Gateway-only mTLS cannot be borrowed; API transfer credentials have an exact non-Browser audience. Gateway placement also needs main-auth-key provisioning or another verification authority and introduces Web-enabled/auth-mode coupling. [ADR D5 candidate brief](../adr/browsercmd-261014-session-browser.md#d5-candidate-brief-authenticated-api-source-for-browser-streaming) records options; the recommended separate API Browser-purpose authenticated source is pending requester decision, not implemented. Decision-independent Runner/UI and REST projection/closure proceed within approved authority. No merge/deployment authorization.
- Environment checkpoint: managed environment ID060d7f0bf5ce4a49/data root f2f504a66ffe46bf remains preserved. Status retained its earlier ready snapshot; fresh `verify` rejected readiness because code changed since launch. Root does not count stored readiness as fresh verification and will restart/reverify the same data after coherent authenticated phase integration is stable, rather than treating incomplete source activation as product readiness. No reset/destroy/import was performed.

## PR-First Delivery Checkpoint (2026-10-15)

- PR #2268 follow-up fixes the two reproduced CI regressions: same-scope
  keyboard/composition events now use the current displayed ACK across a React
  render boundary; shared API fixtures retain deployed logging while Browser
  composition honors existing ordinary Control trust rather than an extra
  environment gate. The same reviewer independently checked the security
  correction with 42 tests; root focused composition/authority tests passed 138.
- Two prepared-image complete viewer runs passed in 75.48 and 75.46 seconds.
  Corrected deployed-API integration reported passing subscription, viewer and
  file assertions; its final process/teardown summary was not returned, so it is
  not reported as a completed successful execution. Required CI is rerun.
- Atomic positive image dimensions prevent a test-side Blob replacement race.
  Native capture diagnostics emit fixed categories only, never SDK error text.
  A previous capture SDK failure is retained as an unresolved diagnostic event,
  not claimed fixed by later successful runs.

- The requester explicitly directed opening the Phase 3 PR first, running CI in
  the background, and continuing the remaining implementation without waiting
  for the local assembled E2E. This changes execution order, not acceptance.
- Complete-diff independent review and targeted correction re-review passed;
  the latter independently ran 91 checks with no material findings.
- Current root checks passed: shared 450, Runner 473, backend 469, Web 521,
  40 real component stories, Storybook build, and all staged pre-commit hooks.
- The matching prepared Runner image has 63 verified source files and 26 SDK
  probe checks; the retained backend image has 2,467 verified source files.
- Final normal-authentication E2E and required CI remain pending. Interrupted
  local runs are not acceptance evidence. Runtime storage eviction was verified
  read-only; no deployment, restart or storage-limit changes were performed.
- Phase 4 begins only after the Phase 3 PR is open. Feature acceptance, spec
  promotion and plan cleanup remain later work. Design delta: None.

## Pre-review Navigation Validation Checkpoint (2026-10-15)

- Root-owned current integrated validation passed: shared runtime-control 449 tests,
  Runner 472 tests, backend 570 tests, Web 519 tests, Web lint/typecheck/format,
  Storybook production build, and documentation catalog/diff whitespace checks.
- The strengthened normal-authentication product E2E passed in 349.62 seconds.
  It covers the Engine-managed Runner/public ingress journey, complete mixed-case
  input, address navigation, native history/reload, dialog/composition, reconnect
  without replay, access revocation and stale target rejection. It is not
  production, real OS mobile IME, or Phase 4 file/publication acceptance.
- Current Runner image:
  `sha256:92791b2086663808aa7c7d01e346a02c833f3ce517f3e732235a2624b23c85e3`.
  All 63 Runner/shared source files match the image. Fresh product-image SDK
  probes passed 11 viewer and 15 inherited Browser checks as uid 1000 with
  Playwright 1.64.0. Sandbox was unavailable in this nested environment; these
  pre-admitted synthetic probes do not establish API source authentication.
- Root reran all 38 actual component stories at DPR 1/scale 1 with loaded product
  fonts; all plays passed with zero accessibility violations or horizontal
  overflow. The final panel-only change was included.
- The requester explicitly rejected page-wide known-input string replacement as
  unagreed behavior and requested its deletion. Root removes that replacement,
  the page input-value collection/state and its obsolete tests. Ordinary page
  content, titles, labels and dialog messages are preserved even when they
  contain text previously entered into a form. M6 structural input-field and
  credential-attribute exclusion, source URL projection and content-free
  generic logs/errors remain unchanged. Runner and assembled E2E evidence above
  predates this removal and must be rerun against matching rebuilt sources.
- Independent review found that a fresh frame ACK could make blur/outside-pointer
  cancellation stale while local held-input state was cleared. Root corrects
  cleanup-only cancellation/release to use the latest ACK only inside the same
  attachment/target/navigation/dimensions; inability to safely dispatch cleanup
  closes the attachment so Runner cleanup releases native state. No effect replay
  or stale spatial action admission is added. Add focused connection and real-hook
  regressions, then rerun affected Web and assembled-product validation.
- Independent review also found shared Runner response demultiplexing awaited
  unbounded Browser authority I/O, and an unacknowledged old-navigation image
  could block all new images. Root moves response admission to bounded per-binding
  freshness, retains bounded fresh pre-effect validation, and monitors each
  attachment within the existing five-second revocation bound. Root retires a
  stale in-flight frame on navigation/viewport change and tolerates only bounded
  ACKs for previously sent retired frames. Add deterministic isolation/timeout
  and actual SDK navigation/resize-before-display regressions; caps and frame
  display authority remain unchanged.
- Corrected assembled E2E exposed a concrete inherited Runner cancellation bug:
  a canceled Browser status task propagated CancelledError through ordinary task
  reaping and terminated the Runner, causing later admission timeout/unavailable
  results. Root fixes expected child-task cancellation reaping while preserving
  parent cancellation and unexpected task exceptions. Add a propagating-cancel
  executor regression proving subsequent same-Runner work proceeds; rebuild the
  matching image and rerun shared/Runner/product evidence without longer deadlines.
- Root owns remaining corrections and shipping; no implementation delegation.
  Exactly `/root/browser-feature-reviewer` reviews the frozen complete diff,
  including untracked files, REQ-15 and navigation clarification. Review,
  commit/push and Phase 3 PR remain pending. No merge/deployment authorization.
- Design delta: None.

## Decision-Independent Integrated Checkpoint

- Owners completed and froze the independent Runner/shared, REST and UI lanes. Public API-source authentication remains unimplemented; no unauthenticated/mocked source or Gateway/transfer credential reuse was introduced.
- Root reran runtime-control full Ruff/format/typecheck and 396 tests; Runner full Ruff/format/typecheck and 469 tests; backend whole typecheck/changed-file Ruff/format plus 101 new REST tests and a 215-test affected regression selection (overlap not summed); Web full lint/format/typecheck, 501 tests and Storybook build. The current non-overlapping reported package selections total 1,581 tests. Documentation and diff checks passed.
- UI owner ran 24 actual-browser static real-component stories: all storyFinished events succeeded, zero axe violations and no horizontal overflow at 1200x900 and 390x844/DPR1. Root visually inspected originals, byte-verified PNG signatures/hashes, and independently checked read-only disabled closure/no text input plus mobile native viewport/no horizontal overflow using a separate named agent-browser Session. That QA Session was closed without closing other browsers. Initial native sandbox startup was positively classified unsupported; the subsequent synthetic UI check used the already-approved unsupported branch without privilege/kernel changes. Mistaken text-label/placeholder waits were corrected using actual labels/selectors and are not counted as passing assertions.
- Root rebuilt image `sha256:2db11a61122d3c566437226a52898f60385720709066e1061ea82309d27fe143` from this frozen uncommitted phase input. A Session-only 65-file source hash manifest preserves the image input identity. UID-1000/Playwright1.64.0 synthetic pre-admitted consumer probe passed 11 assertions: one shared source for two attachments, viewport metadata/no capture files, read-only denial, actual SDK IME commit/guard release, pre-navigation input rejection, dialogs before the first image, null-source consecutive responses, disconnect memory reclamation and native page/context preservation. Separate phase 2 regression probe passed all 15 assertions against the same new image. This is SDK/image evidence, not authenticated public ingress or Engine/Exchange acceptance.
- Local contract correction for required initial-navigation dialogs: ViewerInput.source is required nullable, null is mandatory only for exact dialog responses, and all coordinate/key/composition actions require current acknowledged image source. Human pointer/key-triggered dialogs reuse the original SDK pending handoff. Page/iframe navigation, stale cleanup and late-actor cleanup are fenced. Web and Browser cancel-before-consumer-start resource leakage was fixed with idempotent release and both-domain regression coverage. No new material authority was created by these corrections.
- REST list/close and supporting-panel selection are reachable; production preview explicitly remains unavailable and has no socket/input path. Strict wire/input helpers and connected stories are groundwork. Actual authenticated API/Control/Owner/Runner attachment, live Blob/ACK/input wiring, permission revocation/product E2E and the mandatory full phase 3 review/PR remain pending D5 authority resolution.
- Requirements and accepted Design revision 2 remain unimplemented, with no approval change or phase 3 source activation. Root records the exact blocker/options in ADR D5 candidate brief and requests the requester decision after completing the independent work. No phase 3 PR, merge or deployment was performed.

### Revision 3 implementation checkpoint (2026-10-15)

- The requester selected ADR-D5 option A and explicitly instructed immediate implementation. The independent reviewer audited Design revision 3/M18 authority and feasibility without a blocking finding. The earlier ingress-decision blocker is resolved; no repeat approval gate applies to this disclosed scope. Design delta: None.
- Source, API and UI implementation owners delivered frozen handoffs. Root independently reran runtime-control Ruff/format/typecheck and 396 tests, Runner Ruff/format/typecheck and 469 tests, backend whole-project typecheck and 401 affected tests, and Web format/lint/typecheck, 514 tests and the production Next build. The UI owner additionally verified the Storybook build and 30 actual-browser component stories with no axe violations or horizontal overflow.
- Root built image `sha256:4f8b262f1b84e1273ae57126bbd9bf8b419b6a8b4b2f453c432ce7033b37ce78`; synthetic native regression and viewer probes passed 15 and 11 assertions. They verify actual product Chromium/SDK behavior under UID 1000 with all capabilities dropped and no-new-privileges, but are explicitly not authenticated ingress evidence. Source hashes and logs remain in Session-owned evidence.
- The first assembled authenticated E2E failed at the initial Browser projection with HTTP 500. Actual protobuf roundtrips identified missing Browser request and success arms in the existing Runner operation gRPC translators: the command arrived as an empty payload, and results would also have been empty. This is an integration defect, not an authority decision or a reason to bypass authentication. The source owner is adding dedicated bounded Browser-domain protobuf arms validated through the existing strict command/result codecs, with real serialization/RPC regression coverage. This invalidates the current image and affected shared/backend evidence until rebuilt/rerun.
- The representative E2E now includes normal password login and the real Web panel's authenticated first image, coordinate input and keyboard delivery, in addition to Engine task creation, unrelated-user denial, read-only child input/close denial, exact target mismatch, dialog/composition and fresh reconnect. Collection, E2E Ruff and whole-suite typecheck pass; successful product execution is still pending.
- The preserved development environment ID `060d7f0bf5ce4a49` was restarted without reset after code-provenance verification detected stale running code; all readiness checks returned true. This is readiness, not feature acceptance. No Phase 3 review, commit, PR, merge or deployment has occurred. Root must fix and rerun the assembled product path before freezing the complete diff for the same mandatory reviewer.
- The Runner gRPC correction is complete. Root reran shared full quality/typecheck/434 tests, Runner 469 tests, backend whole typecheck/408 affected tests and another 157 common Control/Owner/relay/server regressions. Composition coverage now explicitly checks Browser RPC registration and its fifth read-only repository factory. Public OpenAPI/Python/TypeScript clients and protobuf outputs were regenerated through project tooling; post-generation Web typecheck passed and all 80 image-source hashes remained identical after protobuf regeneration.
- The matching rebuilt Runner is `sha256:562586662baa8bee15f4b338e859a49cda1b0be4a0f0cc37343fa57aac434e44`; native product-image probes again passed 15 and 11 assertions. The second assembled attempt progressed through actual Engine Browser creation/listing, then correctly rejected a deployed-labelled API using the fixture's plaintext ordinary Control. The local Docker public API fixture now explicitly declares the existing local environment while retaining normal user/resource authentication and mandatory Browser proof; deployed TLS restrictions are unchanged. A third attempt passed the unrelated-user denial and reached child Browser creation, but its test indexed an allocated task before its native page existed. Synchronization now waits for the authoritative page/title projection, without fixed sleeps or relaxed acceptance. The fourth assembled run is in progress.
- The fourth run reached authenticated native pointer/dialog/composition and read-only boundaries, then exposed a real disconnect/reconnect race: binding removal preceded terminal publication while Browser guard cleanup awaited cancellation. A late Runner response could close the shared Runner queue. The fix atomically publishes terminal state, retires Runner mapping before awaiting guard cleanup, rechecks after async authority validation, and ignores only known terminal streams while releasing undelivered buffer reservations. Four deterministic barrier tests preserve unknown-stream rejection and prove fresh source acceptance on the same Runner. Root's complete integrated backend selection passed 569 tests and whole typecheck after this correction.
- The fifth run passed fresh reconnect and normal Web login but the local HTTPS fixture routed only `/chat/` WebSockets to the API. The fixture now routes both closed API domains, `/chat/` and `/browser/`, with the same existing Upgrade/Host/TLS forwarding. The sixth assembled run passed in 85.12 seconds: Engine-created root/child browser resources, unrelated-user and read-only denials, exact target mismatch, authenticated first frames, native dialog/composition, fresh reconnect, normal Web password login/BFF/pointer/keyboard effects, desktop and 390px viewport containment, current authentication-Session logout revocation, preserved native page after fresh login, scoped closure and stale attachment denial. This is local real-product authentication/transport evidence, not production deployment or real OS IME evidence.
- Root inspected the actual successful desktop/mobile screenshots and found a keyboard-quality gap hidden by the initial any-input site assertion: standalone Shift could be forwarded as a held SDK key while textarea text used composition insertion. The UI owner is separating local physical modifiers from effect-bearing remote chords, preserving Shift+Arrow and Ctrl/Meta/Alt shortcuts without weakening the Runner guard or adding input replay. The synthetic site's success title now requires the complete mixed-case GUI text suffix, so a partial delivery cannot satisfy acceptance. The strengthened E2E, affected UI validation and final independent review remain pending.
- At 12:23 KST the requester explicitly rejected the visible standalone input box and the form-like visual quality, directing a proper browser-like interface aligned with the approved concept mock. This is a correction within M16's existing supporting-panel/input authority, not a new navigation API or permission mechanism. Replace the form-style page selector/toolbar stack with compact page tabs, read-only address/status chrome and a dominant framed viewport. Keep the existing Session shell/navigation unchanged. Use a visually hidden IME/mobile receiver focused by viewport interaction; retain physical Tab escape, accessible explicit remote Tab actions, read-only denial, dialog access, current-source fencing and no replay. Do not add decorative nonfunctional controls or new navigation effects merely to resemble a browser. The UI owner will render the real components with product theme/fonts at desktop/mobile sizes; root must inspect those renders and rerun complete-text authenticated input E2E before the phase is considered stable. Design delta: None.
- At 12:33 KST the requester objected to repeated implementation delegation. Root stopped the active UI subagent, confirmed that no implementation subagent remains active, and took direct ownership of all remaining implementation, debugging, visual review and integrated validation. Only the already mandatory single independent feature reviewer remains a later exception. Root directly removed the remaining footer control stack, moved remote Tab commands into the compact keyboard menu, and verified native-resolution real-component desktop/mobile renders with the product Geist font, DPR 1, 100% scale and no horizontal overflow. Web format/lint/typecheck and 516 unit tests passed; actual story plays exposed a menu-transition accessibility capture that is synchronized against real dropdown removal rather than a delay.
- At 12:44 KST the requester identified missing address editing and navigation in the browser-like surface. REQ-15 and the M16 clarification now explicitly cover address entry, native back/forward and actual page reload, distinct from connection refresh. Root directly connects a closed admitted navigation input to the existing M5 Runner structured navigation operations, preserving current acknowledged source/target/generations, read-only denial, task-local guard/dialog handoff, supported HTTP(S) URL validation and non-replay. No new public route, permission, source proof, persistence, Runtime mode or execution backend is introduced. Add codec/Runner/access/UI coverage and a real browser navigation journey; rebuild matching peers and rerun affected integrated validation before the same independent review. Design delta: None.
