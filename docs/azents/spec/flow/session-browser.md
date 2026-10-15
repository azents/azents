---
title: "Session Browser Execution"
created: 2026-10-15
tags: [browser, session, runtime, engine, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, session, toolkit, runtime]
code_paths:
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_runner_wire.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/grpc_runner_client.py
  - proto/azents/runtime_control/v1/runtime_runner_control.proto
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_viewer_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_source_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/grpc_browser_source_client.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_viewer.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py
  - python/apps/azents-runtime-runner/pyproject.toml
  - python/apps/azents-runtime-runner/Dockerfile
  - python/apps/azents/src/azents/engine/tools/browser.py
  - python/apps/azents/src/azents/engine/tools/builtin.py
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/SKILL.md
  - python/apps/azents/src/azents/engine/tools/runtime_io.py
  - python/apps/azents/src/azents/runtime/control_protocol/runner_operations.py
  - python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_server.py
  - python/apps/azents/src/azents/runtime/runner_operation_adapter.py
  - python/apps/azents/src/azents/api/public/browser/v1/__init__.py
  - python/apps/azents/src/azents/api/public/browser/v1/data.py
  - python/apps/azents/src/azents/api/public/browser/v1/websocket.py
  - python/apps/azents/src/azents/core/runtime_browser_source_credential.py
  - python/apps/azents/src/azents/runtime/control_protocol/grpc/browser_source_server.py
  - python/apps/azents/src/azents/services/runtime_browser/authority.py
  - python/apps/azents/src/azents/services/runtime_browser/service.py
  - python/apps/azents/src/azents/repos/runtime_browser_authority_read.py
  - typescript/apps/azents-web/src/features/session-browser/SessionBrowserPage.tsx
  - typescript/apps/azents-web/src/features/session-browser/containers/useSessionBrowserContainer.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserConnection.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserInteraction.ts
  - typescript/apps/azents-web/src/features/session-browser/components/SessionBrowserPanel.tsx
  - typescript/apps/azents-web/src/trpc/routers/browser.ts
last_verified_at: 2026-10-15
spec_version: 1
---

# Session Browser Execution

## Reachable Scope

The Agent has three Runtime-backed browser tool roles: `browser_open`, `browser_observe`, and `browser_act`. They execute through the existing authenticated Runner operation path, not an MCP server or Agent-installed CLI. Public Session Browser projection and scoped page closure use that same command boundary. An independent authenticated live attachment connects the Session Browser panel through the API-owned Browser source to the current Runner. The release-bundled browser Skill guides observation, interaction and original capture publication through existing image and file services.

Browser tools require a current managed Runtime and concrete Session/Run resource authority. Runtime capability guards enforce process/workspace availability, and image observation additionally requires current transfer authority. Projection without current execution authority omits these tools. Each call revalidates access and resolves its actual Session working folder independently of any scheduling/root alias.

## Public Session Projection and Page Closure

The public Browser v1 domain exposes a GET projection and a POST close request beneath `/browser/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}`. Closing `/pages/{page_id}/close` requires the exact `task_id` and `resource_incarnation`; there is no public profile/open/reset API.

Normal HTTP authentication establishes the current user/authentication Session. A completed repository read authorizes the concrete active Agent Session using existing Workspace, Agent, TEAM/USER and root/subagent rules before any task title or content is returned. Public subagent targets are observable but not closable. The root identity used for permission checking never replaces the concrete browser Session identity.

Availability reports `runtime_unavailable`, `browser_unavailable`, or `working_folder_unavailable`. Account/resource denial remains a normal denied/not-found response, not an unavailable projection containing cached titles. Projection does not auto-start a Runtime, allocate a browser context or bind a pending Session folder. It requires the current live Runner generation, reported Workspace, `browser.v1` and an already-bound concrete Session folder.

The service sends typed status/close commands and revalidates current account, Session and Runtime authority before returning the result. Close requires SDK dispatch and the selected target's absence from the returned current list; unknown/failed operations raise rather than masquerading as successful closure or an unavailable read, and are never replayed.

The existing Session supporting panel has a Browser destination using source-generated REST clients through tRPC. Task/page/incarnation links are separate from scheduled-task identifiers. Missing, incomplete or closed requested targets are explicit and do not fall back to another page. Panel dismissal or another destination unmounts the Browser Page without closing browser resources. REST closure permissions are independent of live-preview availability, and errors suppress cached unauthorized content.

## Authenticated Live Attachment

The Browser WebSocket is `/ws` beneath the same concrete Session resource and uses `azents.browser.v1`. Its first text message carries the existing short-lived Chat identity ticket and an exact task/page/incarnation target. Credentials in URL query parameters are rejected. Ticket authentication establishes identity, not resource authority: current account, authentication Session, concrete Session, Runtime generations, working-folder binding and selected live page are checked before source attachment.

Only `azents-api` can open a Browser-purpose source on the existing ordinary Runtime Control listener. Browser-specific credential derivation separates its purpose and audience from transfer credentials and Gateway identity. A fresh Control challenge binds the proof to the connection Hello/profile and one exact Browser OPEN authority. Wrong purpose, peer role, proof, scope, expired setup or a second OPEN is rejected before native effects or admission capacity. There is no new port, durable grant/nonce table, Gateway certificate reuse or main authentication-key distribution.

Connection proof/setup expiry and active attachment lifetime are distinct. The live attachment lasts no longer than one hour or the authenticated Session's expiry, whichever comes first. API and Owner revalidate current joined authority at least every five seconds, with API checks before forwarding input and Owner checks before effect-bearing application frames. Current target/generation checks remain in the Runner. Read-only subagent viewers may acknowledge frames but cannot send input, answer dialogs or close pages.

The source uses existing Owner/relay routing, flow control, capacity, lease/fingerprint and drain boundaries. API source composition reuses the ordinary Control endpoint and CA trust: a configured CA selects TLS even when the existing explicit insecure flag is true; absent CA requires that flag rather than an automatic downgrade. Browser-only proof remains mandatory in every case. Global API Runtime environment/logging does not authorize the source; the isolated Docker fixture retains its normal API environment. Auth/resource/expiry/stale-target termination is distinguished from ordinary source loss. Disconnect or revocation resets only the attachment, releases transient input and volatile frame state, and preserves native tabs, Session profiles and unrelated attachments.

## Live Panel and Input

The panel validates the first status against its exact selected target and attachment before treating the stream as connected. Binary frames carry typed dimensions, navigation and source identity. Image decoding must match those dimensions, and only a displayed current image is acknowledged. One volatile Blob URL and bounded serial inbox are retained; frame bytes are not saved as intentional captures, files, transcripts or image history.

The existing supporting panel presents pages as compact tabs above address/navigation chrome and the framed live viewport. Authorized input participants can enter an HTTP(S) address, go back or forward in the selected page's native history, and reload the actual page. Address drafts are volatile, cleared on blur/target change/submission, and never form an input history. Unsupported schemes and embedded user credentials are rejected. Read-only viewers cannot edit or navigate. Connection refresh is separately labelled and does not claim to reload the site. No standalone page-text entry form is shown.

Navigation is one closed admitted viewer input carrying the same current acknowledged source and sequence. The Runner checks input permission, current source/target/generation and actual held-input conflict before invoking its existing structured navigation/dialog handler. In-flight input blocks another UI navigation without queuing it. New navigation invalidates prior displayed-frame input until the current image is acknowledged; lost actions are not replayed.

Pointer coordinates are transformed against the displayed image and its acknowledged source, excluding letterbox/outside/stale positions. A valid viewport pointer interaction focuses a visually hidden native textarea inside the same focus boundary for text, IME and mobile keyboard events. This receiver is the viewport's single keyboard stop; forward/reverse physical Tab leaves it naturally. Local printable-text modifiers are separated from remote effect-bearing key chords so mixed-case text does not conflict with a held SDK Shift key. Shift+Arrow and Ctrl/Meta/Alt shortcuts still send typed key events.

Keyboard, pointer and composition events carry the current acknowledged source; exact dialog responses carry explicit null source and remain available before a first image. Accessible Send Tab and Send Shift+Tab commands in the compact keyboard menu address the remote page without trapping local focus. Native beforeinput covers mobile Backspace/Delete/Enter. Blur, pointer cancellation and disconnect clean up the attachment's held input and composition without committing cancelled text. Internal viewport/receiver focus transitions do not cancel the interaction.

Input sequences are monotonic and attachment-local. No input payload queue or replay is retained. Ordinary transport loss permits at most three observation-only retries with a fresh ticket, source and sequence; uncertain-action status remains visible. Auth/resource/expiry/stale-target/protocol failures purge unauthorized images/status/cache and do not automatically retry. Read-only UI exposes no effect-bearing callbacks.

Browser source setup has one total deadline of at most ten seconds, including
scope validation, source registration and initial OPEN handling; it is separate
from the attachment lifetime. Owner authority supervision is attachment-local:
two-second validation deadlines and two-second recheck intervals fail closed
within five seconds. The shared Runner response demultiplexer uses bounded
freshness and never waits for Browser database/status-RPC validation. Requests
still require fresh authority before dispatch.

An in-flight image from an obsolete navigation or viewport is retired so it
cannot block the new scope's first image. Each attachment retains at most 128
retired sent-frame sequence numbers solely to ignore delayed ACKs; these ACKs
never establish displayed authority. Unknown ACKs remain invalid.

Non-spatial keyboard/composition input and cleanup can use the newest displayed
ACK only within the same attachment, target, navigation and dimensions, including
the interval before React rerenders after a displayed ACK changes.
If safe cleanup cannot be sent, the attachment closes and Runner releases its
native held state. Spatial effects retain exact displayed-frame fencing.

## Managed Browser Skill

The release-bundled `browser` Skill is projected from the global `release:azents`
source into each immutable Run VFS projection at
`azents://skills/azents/browser/SKILL.md`. Its focused references explain
open/observe, actions/human help and captures/files. Discovery and `load_skill`
use the existing Run authorization and content hash; adding the package does
not install Runtime files or update an older Run's projected content.

The Skill teaches current returned identities, fresh observation after human
interaction, bounded view selection, untrusted page content and separating
dispatched actions from verified outcomes. Native state remains Session-owned;
there is no persistent acquire/return mode or end-of-turn profile cleanup.

Image observation supplies model-visible imagery and an intentional original
PNG. User delivery calls the existing `present_file` path with the actual
returned Runtime path; capture, model materialization and publication have
separate completion/failure semantics. Schema examples are checked against
the strict Browser codecs and all supported provider lowerers.

## Typed Command and Result Boundary

The shared runtime-control library declares frozen operation-specific Browser DTOs and strict codecs. Model-facing schemas have one top-level object. The Engine sends normalized typed commands through `browser.open`, `browser.observe`, `browser.act`, or an internal `browser.list` projection; the latter is not a fourth model tool. Decoding rejects malformed primitive types, missing mandatory fields, unknown fields, unsupported operations and invalid action combinations before effects.

Runner gRPC requests and final successes have dedicated Browser protobuf oneof arms. They carry at most one MiB of canonical UTF-8 Browser-domain bytes, validated through the strict command/result codec on both sides. Integer fields, explicit nulls and empty lists survive the real protobuf roundtrip. Wrong operation/oneof, malformed or duplicate fields, nonfinite values, excessive nesting and oversized payloads fail closed; there is no general JSON or Struct fallback.

Current task/page/resource incarnation and optional frame identity select the target; there is no Runtime-global selected tab or model-controlled Session/profile/debugging endpoint. Element actions carry the current observation identity and stable live element reference. Replaced frames, navigation, detached nodes, closed pages and old manager incarnations invalidate relevant targets/references.

Results contain bounded task/page/frame projections, safe source URLs, current references and observation content, capture/download metadata, and current page-dialog state. `action_state` is explicit: `none` indicates no action dispatch, `dispatched` describes SDK action execution rather than site-workflow success, and `dialog_pending` indicates an outstanding original action waiting for a page-dialog response. Passive condition waits do not claim to have sent input. A pending expected popup/download remains associated with its original trigger and is reconciled after a dialog response.

Runner final failures map to typed, non-secret tool errors. The Engine validates returned page/popup scope and original image location. An unknown result, invalid response or lost Runtime is not retried automatically; the Agent must observe current state before deciding another action. Cancellation uses existing Runtime operation delivery and cancels the applicable work without interpreting it as rollback of a submitted site action.

## Runner Resource Owner

One RunnerBrowserManager belongs to the current Runner connection lifecycle. Registration advertises `browser.v1` only when product browser initialization succeeds; browser unavailability does not stop independent Runner capabilities. Commands validate the current Runtime and accepted Runner generation before resource execution.

Each concrete Session has a separate native persistent BrowserContext/profile under the current Runner Workspace. Tasks within that Session reuse its site state. Session working-folder association cannot change during a live manager's identity. Task-owned pages/popups and frames remain in a live registry with exact resource incarnations, not a durable help/task ownership table.

Native profile bytes remain under existing Runtime persistence; manager/Runner shutdown closes live contexts and invalidates handles without deleting those bytes. Normal Run completion is not profile cleanup. No backup, profile export/replay, retention sweeper or restoration of old live pages exists. Task/page close affects only the intended task resources, not all contexts or other Sessions.

Task capacity is admitted before native context allocation, and page capacity before new page allocation. Failed registration closes the newly allocated page. Closing a task's final page retires its live identity and reclaims task capacity while retaining the Session context/profile.

The Runner application declares a locked Playwright dependency. Image provisioning installs matching Chromium through that environment into the product browser path. System pip/Agent-installed Playwright is not used as product availability evidence. Engine launch preserves the trusted Runner proxy route when configured and does not add a direct-network alternative.

Required Runner host tests also install the matching Chromium/native prerequisites before pytest in CI; the product image does not supply the separate host test environment.

## Supported Observation and Interaction

Open allocates a Session task/page or opens a page in the supplied current task, applies optional navigation, and returns exact live resource identity. It does not claim navigation success merely because a page was allocated.

Observe reports task status or returns current page/frame DOM references, sanitized raw DOM, local readable Markdown glance, or image capture. DOM export preserves safe control structure/labels while omitting input values and unsafe attributes. Glance converts the selected current rendered DOM locally; it does not fetch an authenticated page remotely, invoke another LLM or automatically apply article extraction. Bounds/truncation and source scope remain observable. Detached/unsupported/offscreen content is not represented as complete.

Act performs structured navigation, observed-element input/select/check/key/scroll/hover/drag, scoped page closure, dialog responses, upload, waits and action-associated popup/download handling. Uploads require existing authorized Runtime files. Event expectation registration precedes the trigger. Download completion/failure is verified before returning the saved Runtime file. A captured PNG is not a site's downloaded document.

Navigation and URL waits honor the selected frame. Back/forward/reload, page closure and page dialog responses require the main-page target and reject subframe scope before effects.

Page dialogs have exact current identities. The Runner viewer application contract requires `input.source` explicitly: exact dialog responses require null, while pointer/key/composition input requires current acknowledged image metadata. A dialog before the first image or after navigation therefore remains answerable without fabricating frame identity. A pending dialog suspends the outstanding SDK operation's input-dispatch phase, permitting a scoped response without an operation-wide deadlock. Predetermined/observed responses and expected popup/download completion are reconciled; orphaned pending tasks/references are collected on scoped closure, cancellation and shutdown. Other Sessions can continue while one page dialog waits.

Each response races completion of the original operation against the next dialog. Consecutive dialogs retain that operation and release transient input arbitration at every handoff; cancelling a response drains its tracked original operation without replay.

## Actual Input Conflicts and Conversation Help

The manager's task-local transient interaction guard is the common final boundary for actual overlapping manipulation. It does not establish a persistent human/Agent ownership mode. Continuous composition/gestures can hold one actual interaction until end/cancel; a conflicting actor cannot insert input in the middle. Passive waiting and viewing do not acquire long-lived ownership.

Help and continuation are ordinary Agent conversation/execution behavior: stop the affected manipulation, continue independent requested work if available, otherwise await normal user input; then freshly observe before continuing. There are no acquire/return tools, first-input takeover, help registry, string-keyword ownership protocol or whole-Run interruption. Panel/browser attachment functionality is separate from this Agent command implementation.

## Captures and Existing Delivery

Image observation saves an original PNG in the current Session working context, with exact size/dimensions and bounded capture limits. Credential/password/one-time-code fields are masked in intentional captures. This does not claim universal detection of sensitive page content or alter the live site's account state. Model normalization never overwrites the original.

The Engine uses the existing RuntimeImageReadService and ModelFile-backed FilePart to return actual model-visible image input. A path alone, missing transfer service, oversized image or failed materialization is not successful image observation. The Agent can explicitly invoke existing `present_file` to publish the original through verified Exchange transfer; this command layer does not claim user publication merely because capture succeeded.

Raw page/input data, profile bytes and full sensitive URLs are not copied to generic errors/logs. Observation and original files are intentional content delivery, not continuous live-frame recording.

## Support-Dependent Native Sandbox

Initialization probes native sandbox startup using a blank browser under the current product engine/user/Runtime policy. A successful probe selects sandbox-enabled contexts. Only specifically recognized native sandbox incompatibility selects sandbox-disabled contexts; the unsupported branch is explicitly functional, not equivalent exploit isolation. A missing binary, unrelated startup failure or timeout does not trigger that downgrade. The disabled branch also verifies that the product engine can launch.

The assessment is local to the current manager environment and is re-established after replacement. No user sandbox setting, durable compatibility registry, privileged container change or kernel/AppArmor/seccomp mutation is created. Existing Runtime network and Session/task authority remain applicable in both branches.

## Verification Boundaries

Shared strict DTO/codec, current generations/targets, native Session state, dialog/event/file combinations, observations/capture bounds and transient conflict behavior have focused unit/real-SDK coverage. Engine tests cover full catalog/provider schema lowering, access revocation, current working-folder binding, mandatory action-state/result scope and image failure propagation.

Focused tests and static component stories do not establish assembled-product acceptance. The representative Browser E2E uses normal user creation/login, an Engine-created task, real Runner images and API/Control source admission, a read-only child and unrelated-user denial, native pointer/dialog/composition input, fresh reconnect and the real Web panel. A separate normal-authentication Engine journey verifies actual model imagery, original Runtime PNG identity and authorized Exchange publication/download. The [delivery verification report](../../design/session-browser-verification-report-2026-10-15.md) records completed checks, historical failures and evidence limits. Real iPhone Safari, OS-mobile IME, production deployment and real-site acceptance are not established by these synthetic journeys.
