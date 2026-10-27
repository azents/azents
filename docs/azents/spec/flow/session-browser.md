---
title: "Session Browser Execution"
created: 2026-10-15
tags: [browser, session, runtime, engine, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, session, toolkit, runtime]
code_paths:
  - python/apps/azents/db-schemas/rdb/migrations/versions/f79f6654c302_add_agent_browser_enabled_setting.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/0701fb42b5ce_add_agent_browser_implementation_and_.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_configuration.py
  - python/apps/azents/src/azents/core/browser_configuration.py
  - python/apps/azents/src/azents/repos/browser_configuration.py
  - python/apps/azents/src/azents/services/browser_configuration.py
  - python/apps/azents/src/azents/api/public/agent/v1/browser_configuration.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_controller.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_camoufox.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_mobile.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_geometry.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_install.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_sdk.py
  - typescript/apps/azents-web/src/features/agents/AgentBrowserChoiceSection.tsx
  - typescript/apps/azents-web/src/features/agents/containers/useAgentBrowserChoice.ts
  - typescript/apps/azents-web/src/features/agents/components/AgentBrowserChoice.tsx
  - testenv/azents/e2e/src/tests/required/public/test_browser_configuration.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_runner_wire.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/grpc_runner_client.py
  - proto/azents/runtime_control/v1/runtime_runner_control.proto
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_viewer_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_source_contract.py
  - python/libs/azents-runtime-control/src/azents_runtime_control/grpc_browser_source_client.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_viewer.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_editables.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_input.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser_display.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py
  - python/apps/azents-runtime-runner/pyproject.toml
  - python/apps/azents-runtime-runner/Dockerfile
  - python/apps/azents/src/azents/engine/tools/browser.py
  - python/apps/azents/src/azents/engine/tools/builtin.py
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/SKILL.md
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/scripts/encrypt.py
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/references/confidential-input.md
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/references/open-and-observe.md
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/references/actions-and-help.md
  - python/apps/azents/src/azents/resources/vfs/global/skills/browser/references/captures-and-files.md
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
  - python/apps/azents/src/azents/services/runtime_browser/data.py
  - python/apps/azents/src/azents/services/runtime_browser/service.py
  - python/apps/azents/src/azents/services/runtime_browser/socket.py
  - python/apps/azents/src/azents/repos/runtime_browser_authority_read.py
  - typescript/apps/azents-web/src/features/session-browser/SessionBrowserPage.tsx
  - typescript/apps/azents-web/src/features/session-browser/input.ts
  - typescript/apps/azents-web/src/features/session-browser/connection.ts
  - typescript/apps/azents-web/src/features/session-browser/wire.ts
  - typescript/apps/azents-web/src/features/session-browser/projection.ts
  - typescript/apps/azents-web/src/features/session-browser/popup.ts
  - typescript/apps/azents-web/src/features/session-browser/socketUrl.ts
  - typescript/apps/azents-web/src/features/session-browser/types.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserAddressSelection.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserToolbarTouch.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserEditorViewport.ts
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.tsx
  - typescript/apps/azents-web/src/features/chat/containers/useAgentChatContainer.ts
  - typescript/apps/azents-web/src/features/chat/session-panel/useSessionPanelState.ts
  - typescript/apps/azents-web/src/shared/session-browser/**
  - typescript/apps/azents-web/src/features/session-browser/containers/useSessionBrowserContainer.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserPaste.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserManualKeyboard.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserFieldEditor.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserFieldEditorTransition.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserFieldEditorView.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserKeyboardToolbar.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserFieldVisibility.ts
  - typescript/apps/azents-web/src/features/session-browser/components/BrowserFieldEditor.tsx
  - typescript/apps/azents-web/src/features/session-browser/components/BrowserKeyboardToolbar.tsx
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserConnection.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserInteraction.ts
  - typescript/apps/azents-web/src/features/session-browser/native-text.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserTouchView.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserDirectTouch.ts
  - typescript/apps/azents-web/src/features/session-browser/containers/useBrowserTouchView.ts
  - typescript/apps/azents-web/src/features/session-browser/recentTargets.ts
  - typescript/apps/azents-web/src/features/session-browser/components/SessionBrowserPanel.tsx
  - typescript/apps/azents-web/src/trpc/routers/browser.ts
last_verified_at: 2026-10-27
spec_version: 1
---

# Session Browser Execution

## Reachable Scope

The Agent has three Runtime-backed browser tool roles: `browser_open`, `browser_observe`, and `browser_act`. They execute through the existing authenticated Runner operation path, not an MCP server or Agent-installed CLI. Public Session Browser projection and scoped page closure use that same command boundary. An independent authenticated live attachment connects the Session Browser panel through the API-owned Browser source to the current Runner. The release-bundled browser Skill guides observation, interaction and original capture publication through existing image and file services.

Browser tools require a current managed Runtime, explicit Agent `browser_enabled`
opt-in and concrete Session/Run resource authority. Existing and new Agents default
to disabled; an authorized manager enables Browser in Agent Runtime settings.
Disabled Agents omit all three Browser tools and all Browser-use UI entry points: the supporting-panel Browser destination, its live/page content and historical tool-result Open in Browser actions. The enabling control remains in Agent Runtime settings. Direct or stale `page=browser` links on a disabled Agent resolve to Files, clearing Browser target parameters while retaining unrelated query state. Current Agent flag changes unmount Browser content and remove action links; this does not close native tabs, erase profiles, redact tool history or restart the Runtime. Scoped action-link availability defaults to disabled without a current Agent flag. Already projected handlers recheck
the current setting before dispatch, and API/Control live admission and periodic
revalidation use that same current setting. Disabling does not delete profiles or
stop unrelated Runtime features. It is a product capability switch, not a sandbox
against arbitrary Runtime shell access.

Runtime capability guards enforce process/workspace availability, and image observation additionally requires current transfer authority. Projection without current execution authority omits these tools. Each call revalidates access and resolves its actual Session working folder independently of any scheduling/root alias.

## Per-Agent Browser Engine

Agent Runtime settings offer Patchright (default) and Camoufox (experimental,
explicit opt-in). Both engines ship in the Runtime image. The choice applies to
every Session of the Agent and does not change `browser_enabled`, Runtime identity,
Runner generation, infrastructure configuration authority, or Runtime capability.

GET and PUT `/agent/v1/workspaces/{handle}/agents/{agent_id}/browser-configuration`
return the opaque current intent, requested/applied engine, current Runtime and
Runner generation, and `offline`, `applying`, `ready` or `failed` state with a
bounded reason. PUT accepts a closed replacement with `expected_intent_id`,
`implementation` and explicit `retry`. Existing Agent access checks protect reads;
Agent administrators manage the choice. Stale-intent replacement is rejected.
The UI confirms browser retirement before saving, distinguishes requested from
applied state, and exposes explicit retry without promising site compatibility.
When Session Browser is disabled, the engine selector is disabled and selection,
confirmation and retry handlers cannot save a change. Application status and
previous switch errors are hidden until Browser is enabled again. The saved
engine choice and the Session Browser enabling control remain unchanged.

Saving first persists Agent-owned intent, then immediately attempts browser-only
application. A durable leased reconciliation task and current Runner state reports
resume pending work after offline periods or control loss. Application queries
current Runner status before deciding whether configuration is still needed;
a lost response does not replay website actions or restart an already-applied
browser. Claims and admission are fenced by exact intent and current Runtime,
infrastructure configuration and Runner evidence, not a new browser version
counter. Browser operations cannot start until the exact intent is ready.

The Runner serializes transitions, revokes live viewer sources and transient
inputs, retires task/page/frame identities and pending browser work, closes old
contexts/display/driver resources, and starts only the requested engine. Shells,
PTYs, unrelated jobs and Runtime files continue unchanged. New native startup
failure is visible and does not fall back to Patchright. Existing browser profile
bytes remain; each engine has a separate per-Session profile and no cross-engine
profile migration. Switching back can reuse that engine's cookies, never its old
live tab identities.

## Public Session Projection and Tabs

The public Browser v1 domain exposes a GET projection and POST tab creation/closure beneath `/browser/v1/workspaces/{handle}/agents/{agent_id}/sessions/{session_id}`. Posting an empty closed request to `/pages` creates one blank tab through the existing Runner open command and returns its exact page identity with the current projection. It creates a task labelled Browser, consumes ordinary task/page capacity, accepts no URL or authority override, and never starts a stopped Runtime. Closing `/pages/{page_id}/close` requires the exact `task_id` and `resource_incarnation`. There is no profile/reset API.

Normal HTTP authentication establishes the current user/authentication Session. A completed repository read authorizes the concrete active Agent Session using existing Workspace, Agent, TEAM/USER and root/subagent rules before any task title or content is returned. Public subagent targets are observable but cannot create or close tabs. The root identity used for permission checking never replaces the concrete browser Session identity.

Availability reports `runtime_unavailable`, `browser_unavailable`, or `working_folder_unavailable`. Account/resource denial remains a normal denied/not-found response, not an unavailable projection containing cached titles. Projection does not auto-start a Runtime, allocate a browser context or bind a pending Session folder. It requires the current live Runner generation, reported Workspace, `browser.v1` and an already-bound concrete Session folder.

The service sends typed status/open/close commands and revalidates current account, Session and Runtime authority before returning the result. Creation requires the returned page to be present in the current task list. Close requires SDK dispatch and the selected target's absence from that list. Unknown/failed operations raise rather than masquerading as successful creation/closure or an unavailable read, and are never replayed.

The Session supporting panel has a Browser destination using source-generated REST clients through tRPC. Task/page/incarnation links are separate from scheduled-task identifiers. A valid explicit live tab wins. Missing, malformed or closed links select the most recently worked live Agent tab known from a bounded authorized snapshot of the latest 100 history events and current partial live history; when unknown, the first live tab is selected. Event results supply preference only and must match the current projection exactly. Target rejection excludes that exact identity from the local candidates and refreshes the projection. A replacement tab always receives a fresh independently admitted attachment, never replayed input. No tabs shows an empty state with a New tab action, disabled for read-only viewers. Each tab has its own close button and the strip has a New tab button. Successful creation selects the returned exact new page; closing the active tab reuses the default selection rule. Panel dismissal or another destination unmounts the Browser Page without closing browser resources. REST tab permissions are independent of live-preview availability, and errors suppress cached unauthorized content.

When the Agent is deleting or has a deletion error, the Browser UI explicitly enters
the [Agent read-only state](../domain/agent-deletion.md#public-status-and-read-only-admission).
It suppresses new tickets, reconnect/attachment (including after an awaited ticket or
WebSocket open), navigation/input and pending-input replay. Existing output and local
panel navigation remain inspectable where native Runtime authority permits them.
Read-only presentation never starts or recreates a Runtime merely for inspection.

## Browser Automation Markers

Default Patchright Session contexts use installed full Chromium in
headed mode, retaining the existing sandbox/proxy policy and driver defaults.
Before admitting a newly launched persistent context, the Runner awaits Chromium's
initial GPU-information completion through the SDK's public browser CDP session
and detaches that session. Launch and initialization share the pinned SDK's
180-second launch budget;
native watchdogs or disconnection can fail earlier. Startup failure closes the
unpublished context and reports `browser_unavailable`; cancellation remains
cancellation. The response is discarded, not logged or used as a fingerprint.
This startup barrier is not a warming screenshot or a guarantee about later GPU
restarts and new surfaces. SDK font preparation, the two-second live capture
deadline, fresh pixels, background visibility, and explicit capture failures remain
unchanged. Reduced Runtime/Console instrumentation remains Patchright-owned.
The Runner uses the
browser's native User-Agent, client hints, language and GPU identity rather than
injecting fingerprint overrides. Product DOM observation and private field
geometry/editing scripts remain separate browser functionality.

Experimental Camoufox contexts use the pinned Camoufox SDK and official
Firefox-based distribution through the native Playwright boundary, including the
SDK's packaged fingerprint-generation model. Explicit viewport/window geometry
matches the viewer coordinate plane. This backend does not run the Chromium GPU
startup query. Both backends use native opener-scoped popup events. The product
does not add page-world interception, infer popup ownership from URLs or promise
successful access to a particular site.

On Linux without a supplied DISPLAY, the browser manager starts one owned Xvfb,
waits for its bounded displayfd readiness record and passes that display only to
its browser children. Xvfb has no TCP listener; native display selection and
non-Linux hosts are not replaced. Failure disables browser availability rather
than silently changing to headless or another driver. Manager cleanup closes
contexts and the driver before terminating and reaping its owned display.
Browser startup failure also releases the display. Independent Runner capabilities
remain available when browser initialization fails.

This is not an authorization change, CAPTCHA solver, proxy rotation, or guarantee
of undetectability or site access. Chromium CDP remains in use. Automatic console
collection is not part of the Browser command contract. Existing profile bytes
remain in place; the launch policy applies to newly created native contexts.

## Authenticated Live Attachment

The Browser WebSocket is `/ws` beneath the same concrete Session resource and uses `azents.browser.v1`. Its first text message carries the existing short-lived Chat identity ticket and an exact task/page/incarnation target. Credentials in URL query parameters are rejected. Ticket authentication establishes identity, not resource authority: current account, authentication Session, concrete Session, Runtime generations, working-folder binding and selected live page are checked before source attachment.

Only `azents-api` can open a Browser-purpose source on the existing ordinary Runtime Control listener. Browser-specific credential derivation separates its purpose and audience from transfer credentials and Gateway identity. A fresh Control challenge binds the proof to the connection Hello/profile and one exact Browser OPEN authority. Wrong purpose, peer role, proof, scope, expired setup or a second OPEN is rejected before native effects or admission capacity. There is no new port, durable grant/nonce table, Gateway certificate reuse or main authentication-key distribution.

Connection proof/setup expiry and active attachment lifetime are distinct. The live attachment lasts no longer than one hour or the authenticated Session's expiry, whichever comes first. API and Owner revalidate current joined authority at least every five seconds, with API checks before forwarding input and Owner checks before effect-bearing application frames. Current target/generation checks remain in the Runner. Read-only subagent viewers may acknowledge frames but cannot send input, answer dialogs or close pages.

The source uses existing Owner/relay routing, flow control, capacity, lease/fingerprint and drain boundaries. API source composition reuses the ordinary Control endpoint and CA trust: a configured CA selects TLS even when the existing explicit insecure flag is true; absent CA requires that flag rather than an automatic downgrade. Browser-only proof remains mandatory in every case. Global API Runtime environment/logging does not authorize the source; the isolated Docker fixture retains its normal API environment. Auth/resource/expiry/stale-target termination is distinguished from ordinary source loss. Disconnect or revocation resets only the attachment, releases transient input and volatile frame state, and preserves native tabs, Session profiles and unrelated attachments.

## Live Panel and Input

Routine Browser status stays compact. While the connected page is waiting for
current pixels, a small noninteractive loading indicator replaces explanatory
text over the image; its accessible name announces the update. Stale/disconnected
images retain their existing input fences and dimming. The header reports
connection/read-only state without repeating a status paragraph over or below
the image. A missing image shows one concise connection/loading status. Actual
failures and unconfirmed action outcomes remain visible with a short next action.
Empty pages rely on the New tab control instead of instructional copy.
The private editor explains only that Apply commits the change, without repeating
direct-input or single-field implementation details. Browser-engine controls retain
the experimental option label and disruptive-switch/profile warnings, without
duplicating an experimental/popup-selection helper paragraph.

Local keyboard receivers retain only their own transient typed text tail while
focused. Ordinary input is reconciled against that tail rather than clearing the
textarea after every event. This preserves native Korean replacement on iOS,
including insert/delete sequences without composition events. Composition commits
and their following duplicate input event insert text once. A changed tail uses
grapheme-aware suffix replacement: the closed `text_edit` action carries a positive
`delete_before` count (at most 32,768) and replacement text (at most 32,768
characters), never a remote field snapshot. The Runner selects the native preceding cursor units and applies Backspace
and insertion under one task interaction guard and a ten-second effect deadline.
Selection avoids treating Firefox's partial emoji Backspace as deletion of a whole
local grapheme.
Partial/unknown effects are not replayed. Held input conflicts, source fences and
the whole-message bound still apply. Local blur/cancellation, receiver change,
remote caret/key chords, document/attachment changes and access loss discard the
tail. Typed text is absent from React state, telemetry and history.

The address field requests the native URL keyboard through URL type/input mode,
with capitalization, autocorrect and spellcheck disabled. Exact shortcut keys
remain an OS/keyboard choice.

The panel validates the first status against its exact selected target and attachment before treating the stream as connected. Binary frames carry typed logical CSS dimensions, navigation and source identity. Decoded image dimensions must be a uniform integer density of 1× or 2× those dimensions and remain within sixteen million pixels; the JPEG itself carries the raster dimensions without changing the transport header. Only a displayed current image is acknowledged. Live images use native device-pixel capture at JPEG quality 85. The fixed 400×560 content plane renders at 800×1120 pixels; local aspect fit, input and editable coordinates remain CSS-based. Capture scratch budgeting includes the fourfold device-pixel area. The image element is retained across live frame replacement. The displayed Blob URL remains valid while at most one replacement decodes; the old URL is released after successful display, and both are released on clear/disposal. The serial inbox remains bounded; frame bytes are not saved as intentional captures, files, transcripts or image history.

For rollout, the web client that accepts both image densities must reach users before the 2× Runner is enabled. Already loaded older web tabs require a reload: their exact-size image check rejects 2× images. The relay header is unchanged, so the API needs no density-specific protocol change.

Transient browser warnings (invalid address, close/create/edit failure, interaction conflict and unknown input outcome) appear as compact accessible notices over the browser surface. Their appearance and removal do not change the address bar, viewport dimensions, aspect fit or input coordinates; empty space around notices remains pointer-transparent. Notice content accepts local pointer/touch scrolling and the notice stack is keyboard-focusable so wrapped or multiple messages remain reachable in short viewports; scrolling is contained locally. Paste feedback remains a compact dismissible overlay. Native site dialogs retain their separate interactive confirmation/prompt surface.

The supporting panel presents browser-style tabs above address/navigation chrome and an unframed live image. Controls retain internal padding; the image has no outer margin or decorative border. Preview content does not send remote input: activation opens focused viewing and consumes that gesture locally. Authorized input participants can enter an HTTP(S) address, go back or forward in the selected page's native history, and reload the actual page. The address field smoothly expands while focused by collapsing the preceding navigation controls and restores on blur/submission; reduced motion disables the transition. Address drafts are volatile, cleared on blur/target change/submission, and never form an input history. Unsupported schemes and embedded user credentials are rejected. Read-only viewers cannot edit or navigate. Connection refresh is separately labelled and does not claim to reload the site. No standalone page-text entry form is shown.

Navigation is one closed admitted viewer input carrying the same current acknowledged source and sequence. The Runner checks input permission, current source/target/generation and actual held-input conflict before invoking its existing structured navigation/dialog handler. Ordinary typing acknowledgements do not toggle navigation controls or address editability. One explicit navigation intent may wait locally for already-sent input and cleanup acknowledgements; further effect-bearing input and a second navigation are blocked while it drains or executes. It is sent once only if those acknowledgements succeed in the same live page/document/geometry scope. Rejection, unknown outcome, dialog/conflict, document change or disconnect discards an unsent intent; reconnection never replays it. New navigation invalidates prior displayed-frame input until the current image is acknowledged; lost actions are not replayed.

Main-page navigation changes the viewer navigation identity. Subframe navigation
invalidates that frame's element references without replacing the main-page viewer
identity, so an independently navigating embedded frame does not invalidate
text input on an unchanged main page.

Focused viewing is an independent body-level modal that covers the global app bar and fills the visual viewport, without outer margins. Safe-area padding and visual viewport resize/scroll observations keep its explicit text Exit focused view button reachable when the mobile keyboard changes available space. That control is separate from per-tab closure. Focus is contained locally and Escape exits unless an IME composition is active. Modal presentation does not reopen the Browser attachment or resize the native page. Both preview and focused viewing aspect-fit the complete source image to the available width and height at 100%, preserving its native ratio and centering unused letterbox space outside the input plane. The native page does not resize when its container changes. Focused local viewer zoom ranges from 100% of that fitted size to 300%, through continuous pinch, Ctrl+wheel, or 25% menu steps. Ctrl+wheel is intercepted only within an enabled focused viewer, prevents host-page zoom, and sends no remote wheel action; ordinary wheel remains remote page scrolling. Zoom anchors use the actual image geometry, including letterbox offsets. Enlarged content is locally panned by touch or left-mouse dragging; stationary mouse taps still activate the remote page. The viewer container hides scrollbars and does not expose ordinary container scrolling. Reset restores the fitted frame and clears local pan offsets. All remote coordinates use the actual image bounds, never unused letterbox space.

Default touch input has an attachment/navigation-scoped tap/pan/pinch state machine. A stationary single-finger tap sends one source-fenced remote down/up pair. Only a directly touched known editable receiver uses native trusted touch focus; other image taps do not request the software keyboard. Repeated input taps do not blur/refocus the receiver. Beginning a single-finger image gesture retains the current native receiver's focus so a pan can scroll while the keyboard stays open; only a completed non-editable tap or a two-finger pinch blurs it. No remote press is held while waiting to distinguish a tap from a gesture. One-finger movement scrolls the remote page at 100% or pans the local enlarged image above 100%. Two fingers pinch the local image around their midpoint, sending no remote click. Pinch completion, cancellation, target/navigation changes, access changes and disconnect discard incomplete gestures. Only completed finger taps show the brief circular feedback; mouse clicks and pinch/pan do not. A fixed-size central dot marks the exact tap coordinate while the surrounding ring expands; the dot holds its position and size until fading out with the feedback. Feedback never intercepts input and reduced motion uses a static fade. The feedback denotes the physical tap, not confirmed remote action success.

Focused viewing can explicitly enable direct touch from the existing upper Browser actions menu. Normal touch browsing remains the default; no bottom toolbar, permanent mode row or helper strip is added. Only while enabled, a compact hand indicator beside that menu exposes turn-off or release. Direct touch maps one finger to native left-button down immediately, held movement, then up on lift. Pending input acknowledgements are labelled as sending rather than confirmed hold. This local interpretation mode grants no permission or persistent ownership; actual held gestures retain the existing task interaction guard.

A second finger, movement outside the displayed image, pointer cancellation/capture loss, or explicit release ends a direct press without synthesizing another click. After interruption, remaining contacts must lift before a new press. Blur/background, focused-view exit, attachment/document changes, access loss and disconnect clean up and reset to normal touch browsing; ordinary frame updates do not reset the mode. Uncertain or rejected actions are not replayed. Release ends held input, not site effects already caused by pressing or dropping. Zoom/navigation cannot overlap an active direct touch press. Keyboard/edit/paste and mouse input otherwise retain their existing contracts.

Pointer coordinates are transformed against the displayed image and its acknowledged source, excluding letterbox/outside/stale positions. Synchronous DOM input resolves the latest actually displayed frame at event dispatch, even when React still holds an earlier render's frame number. This is allowed only within the same attachment, task/page/incarnation, document and dimensions; decoding-only replacement images and stale geometry never authorize input. Explicit frame-bound operations retain their exact source checks. Each frame carries at most sixteen content-free native editable rectangles with document-local identity and input mode. Native input/textarea receivers use an inner rectangle inscribed within computed rounded corners, including normalized percentage/elliptical radii. Clipping and corner/edge-midpoint/center hit tests apply to the published receiver, so noninteractive rounded corner pixels do not exclude an otherwise eligible field and overlays are not accepted by a center-only test. Unknown radius geometry fails closed. Bounded open-shadow and untransformed iframe traversal excludes disabled, read-only, occluded, clipped-away and uncertain targets. Unstable capture geometry omits receivers while streaming the image. Local transparent textareas retain identity across ordinary frame/visual-viewport updates and retire on document/attachment changes. The visually hidden generic receiver defaults to `inputmode=none`; it remains the viewport's keyboard stop and physical Tab leaves it naturally. Local printable-text modifiers are separated from remote effect-bearing key chords so mixed-case text does not conflict with a held SDK Shift key.

Focused viewing provides a Show keyboard action independently of native editable membership. In the explicit trusted click/touch gesture it synchronously focuses the local generic receiver with textual input mode; it does not click, refind or move remote focus. Subsequent text follows the existing source-fenced direct-input stream to the remote page's current focus. A separate stable generic receiver reference avoids activating a previously selected field overlay by mistake. Local blur, target/document/attachment change, hidden page, access loss, disconnect and unmount reset its mode and contents; streaming frame-sequence changes alone do not. Existing input authority, active-dialog and stale-image checks govern activation. The action does not grant unrecognized targets private Edit/Paste eligibility, read values or retain a preference. Native software keyboard availability remains browser/OS controlled.

Patchright and Camoufox share the same popup-follow policy through the native page's `popup` event. An input-capable live attachment expresses interest in its observed page; subsequent ordinary foreground human input renews that interest. Popups from that exact opener nominate the interested attachment for selection, including script-opened tabs and slow initial responses arriving after mouseup. This is a viewing preference, not proof that a click caused the popup. No Chromium target-creation session, URL matching, elapsed-time heuristic or page-world interception is used for selection. Explicit Agent `expect=popup` still associates its popup with its trigger independently.

Modified/middle-button background intent suppresses follow until ordinary foreground input resumes. Agent effects retire that page's human interest and existing hint, so their immediate or later scripted popups cannot reuse it until human input resumes. Another source page has independent interest and cannot publish a hint for this attachment. Input cancellation/disconnect and document changes retire interest; a new attachment never receives a previous attachment's hint. Human toolbar navigation renews interest after its own cleanup.

The web refreshes projection and selects a hinted live tab only while the originating resource/page/incarnation, attachment, navigation and hint are current. Explicit user tab choice synchronously dismisses hints for the old attachment before routing completes, including a hint that arrives after that choice. Fresh foreground input can resume follow, without replaying a dismissed hint. Popups that open after human input resumes follow the current viewing preference; native popup events do not distinguish script provenance or prove ownership by an earlier action.

Direct input remains the default. Selecting a current native editable exposes one compact lower floating Paste/Edit pair; the connected panel removes the duplicate upper Paste control. Paste invokes a feature-detected clipboard read directly in the trusted gesture; browser/OS consent remains native. Local keyboard/callout `paste` consumes only authorized `text/plain`, clears the receiver, prevents duplicate local insertion and does not forward Ctrl/Cmd+V to the remote clipboard. Both direct routes submit a typed paste action with the editable ID and unchanged text on the existing Browser stream. Runner verifies acknowledged-region membership, current native focus through the frame/shadow chain and existing input authority immediately before `keyboard.insert_text`. A delayed read cannot follow a changed receiver, document, attachment or target. Clipboard text is absent from telemetry, files, Agent events and history; only the explicit native editor can retain pasted text in its transient draft. Empty/oversized/denied/unsupported/stale outcomes do not fabricate successful insertion. Routine clipboard/completion/cancellation banners are not shown. The existing 32,768-character and 64-KiB whole-message bounds apply without truncation. Native insertion emits input rather than a custom remote paste event; rich clipboard/editor semantics and remote-to-local copy are not implemented.

Edit explicitly reads one focused native textual input or textarea through private `field_open`/`field_value` messages, correlated with the attachment-local input sequence and successful acknowledgement. Frame/status/projection metadata contains no complete values. API ingress requires a matching explicit open, exact editable/attachment/sequence, one private response, current input authority and existing size limits. The Runner retains one transient exact-element/document/original-value snapshot. Contenteditable, custom editors and unsupported native types are rejected rather than flattened.

The private read includes a closed bounded native-attribute record: original supported input type, input mode, autocomplete, effective capitalization/correction, spelling, enter-key hint, min/max length, pattern, required/multiple, placeholder and name. Effective native IDL values preserve associated-form behavior instead of inventing inheritance from generic ancestors. The web maps only these hints, not arbitrary page attributes, scripts, form associations/actions, original DOM IDs or styles. An email input remains `type=email` with its original autocomplete hints; actual keyboard/autofill suggestions remain browser/OS/local-origin controlled. The hints do not retrieve credentials saved for the remote site's origin.

The full-screen native editor masks password inputs and preserves multiline values, local selection, composition and the native Paste menu. Explicit local Paste inserts through the native editing command and takes draft state from the actual control, including email inputs without `selectionStart` support; no blind append or differently sanitized hidden draft is used. Unsupported insertion does not fabricate success and leaves native OS Paste available. Apply sends one `field_replace`, including an intentional empty string, and keeps the modal read-only until acknowledgement. Runner consumes the edit handle and verifies original element, focused frame/shadow ancestry and current document. Matching captured native prototype getters/setters govern original-value comparison, writable eligibility, editing configuration, supported type/password classification and mutation, so instance wrappers cannot hide a changed native value or unmask a native password. A detached same-type/configuration control must represent the draft exactly before any original-field event or mutation. Runner then dispatches cancellable `beforeinput`, repeats validation/representation checks, sets the native value and emits `input` in one document turn. Site handlers may subsequently validate/transform the input; dispatch does not confirm a site's later workflow. Cancel discards the snapshot without changing the field. Replacement is never replayed, including on uncertain outcome.

Target/document/authority/connection loss, ordinary direct effects and lost editable membership retire private editing state. A validated new frame that loses the original editable identity immediately clears the local draft and retires the attachment, including child-document changes that keep the top navigation identity. Runner acknowledgement of lost membership also disposes its snapshot. Values are transient, excluded from generic live state and diagnostics, and never exposed through Agent history. Content-free rejection feedback uses the panel's existing error area; it does not add routine status banners.

The editor uses an opaque theme-body background through the layout viewport, with short enter/exit opacity transitions and zero duration for reduced motion. Normal close retains visual content only through exit; security invalidation removes sensitive content immediately. VisualViewport bounds the lower controls and modal without assuming keyboard height. Local viewing-space reveal keeps the selected receiver and nearby label context above the controls, and does not send remote scroll input or undo subsequent participant scrolling. Initial address focus/re-entry selects the complete URL; later native caret/range edits are preserved. These controls do not repair the separate direct multilingual IME path, and physical iPhone Safari keyboard/candidate/clipboard continuity still requires device acceptance.

Keyboard, pointer and composition events carry the current acknowledged source; exact dialog responses carry explicit null source and remain available before a first image. Accessible Send Tab and Send Shift+Tab commands in the compact keyboard menu address the remote page without trapping local focus. Native beforeinput covers mobile Backspace/Delete/Enter. Blur, pointer cancellation and disconnect clean up the attachment's held input and composition without committing cancelled text. Internal viewport/receiver focus transitions do not cancel the interaction.

Input sequences are monotonic and attachment-local. No input payload queue or replay is retained. Ordinary transport loss permits at most three observation-only retries with a fresh ticket, source and sequence; uncertain-action status remains visible. Auth/resource/expiry/stale-target/protocol failures purge unauthorized images/status/cache and do not automatically retry. Read-only UI exposes no effect-bearing callbacks.

Browser source setup has one total deadline of at most ten seconds, including
scope validation, source registration and initial OPEN handling; it is separate
from the attachment lifetime. Owner authority supervision is attachment-local:
two-second validation deadlines and two-second recheck intervals fail closed
within five seconds. The shared Runner response demultiplexer uses bounded
freshness and never waits for Browser database/status-RPC validation. Requests
still require fresh authority before dispatch. Initial admission verifies the exact
native task/page/incarnation through a selected-page status operation. Live
revalidation refreshes identity, Session access, Browser opt-in, Runtime and
working-folder authority without issuing another Browser operation for every
input message. Runner independently fences the existing native Session binding,
exact target, generation and acknowledged source immediately before effects.

An in-flight image from an obsolete navigation or viewport is retired so it
cannot block the new scope's first image. A capture whose native document
loses its execution context or frame is discarded even before the
navigation event arrives; the regular next frame observes the current document,
without replaying input. Other capture errors still fail the source.
Each attachment retains at most 128
retired sent-frame sequence numbers solely to ignore delayed ACKs; these ACKs
never establish displayed authority. Unknown ACKs remain invalid.

Non-spatial keyboard/composition input and cleanup can use the newest displayed
ACK only within the same attachment, target, navigation and dimensions, including
the interval before React rerenders after a displayed ACK changes.
If safe cleanup cannot be sent, the attachment closes and Runner releases its
native held state. Spatial effects retain exact displayed-frame fencing.

## Managed Browser Skill

### Delegated confidential field input

Browser `fill` accepts exactly one of literal `text` or `encrypted_text`.
Encrypted input is explicit and fill-only; Base64-like ordinary text remains
literal. Ciphertext passes unchanged through the server, tool history and Control
codec. After current target, observation and interaction admission, the Runner
decrypts into a local value for the native fill call. Invalid ciphertext and
confidential native SDK errors return fixed value-free errors without a plaintext
fallback or automatic replay.

One recipient key pair belongs to the Runner process. Recreated transport and
Browser managers reuse it; process exit loses the private key. New Agent command
processes receive the public key in `AZENTS_BROWSER_INPUT_PUBLIC_KEY`, applied
after normal environment composition. The private key is not persisted or put
in command environment. Terminal environment behavior is unchanged.

The release Browser Skill includes `scripts/encrypt.py`. The Agent imports
`azents://skills/azents/browser/scripts/encrypt.py` through existing current-Run
VFS transfer and executes the actual returned Runtime path using
`uv run --no-project --script ... --env VARIABLE_NAME`. Inline metadata supplies
PyNaCl in a Runtime-side script environment. The Runner separately depends on
PyNaCl for decryption; its internal interpreter is not an Agent helper contract.
The script reads the named value and public key internally, accepts up to 4096
UTF-8 bytes, and prints one padded URL-safe Base64 ciphertext line. SealedBox
ciphertext is bounded to 4144 bytes / 5528 encoded characters.

Skill guidance covers dependency prerequisites, process completion/polling and
copying stdout unchanged into `encrypted_text`. Package access follows current
Runtime policy. Missing prerequisites or an incompatible old Runner fail without
weakening that policy. Older Runs retain their projected resources; loading a
Skill does not materialize a script, mutate the projection or install packages.

Environment provisioning still delegates reading and use to the Agent. This
reduces routine plaintext propagation, not the Agent's existing authority or the
receiving site's ability to see or later echo input. There is no key registry,
vault, one-use ledger, expiration, domain allowlist or new approval ceremony.

### Source projection

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

One browser controller and its native managers belong to the Runner process, not
the Control connection. Registration advertises browser support independently of
current intent readiness. Browser unavailability does not stop independent Runner
capabilities. Commands validate the current Runtime and accepted live connection
generation before resource execution.

Control transport loss synchronously fences former authority and cancels admitted
browser effects. Connection teardown drains commands, viewer attachments and
pending dispatch waits, releases held input and private editor state, and disposes
old observation refs. It retains native contexts, tabs, page memory, profiles and
surviving task/page/incarnation identities. Dialogs are not automatically answered
and uncertain website effects are not replayed. A stable nullable epoch callback
follows the current transport/registration rather than a former RunLoop. New
admission waits for cleanup and the existing current-intent readiness reconciliation
in the new generation; same-intent reconciliation does not restart the browser.
Unconfirmed browser cleanup fails the current intent closed without silently
replacing native resources. Final Runner exit and explicit engine transitions
still retire native resources; actual unconfirmed retirement keeps its existing
sticky failure boundary.

API and Owner live scope distinguish current, temporarily unavailable, revoked and
expired authority. Connection epoch loss ends the old attachment with transient
transport semantics and permits fresh admission through existing bounded retries;
it does not mark a surviving native target closed or an account revoked. Actual
access loss/expiry and native target closure retain their denial boundaries.
Agent tool errors describe connection unavailability or changed authority, not
physical Runtime recreation inferred solely from generation changes.

Each concrete Session and selected engine has a separate native persistent BrowserContext/profile under the current Runner Workspace. Tasks within that Session/engine reuse its site state. Existing Patchright profiles retain their location; Camoufox uses a distinct engine-specific location. Session working-folder association cannot change during a live manager's identity. Task-owned pages/popups and frames remain in a live registry with exact resource incarnations, not a durable help/task ownership table.

Both engines launch a fixed 400×560 CSS-pixel portrait content plane with a mobile user agent, matching screen dimensions, touch capability and device scale factor 2. Patchright uses Chromium's native mobile emulation. Camoufox uses its native navigator/screen/window configuration and Firefox touch, meta-viewport and coarse-pointer preferences; it remains the selected desktop Firefox engine, not an Android browser binary. Camoufox's outer window is 400×660, leaving room for native chrome, and generated window dimensions cannot clip the input plane. Existing persistent profile bytes are retained. Local aspect fit, focus, container resize and viewer zoom never change this remote geometry. These settings do not promise compatibility with site security challenges. On mobile Chromium pages without a responsive viewport declaration, the SDK layout viewport may be wider than the captured content plane. Viewer pointer/wheel coordinates are converted through the native visual viewport scale and offsets before SDK dispatch; native editable rectangles are inversely projected into captured-frame pixels after frame-to-main-page projection. Structured Agent element actions retain their native SDK coordinates.

Native profile bytes remain under existing Runtime persistence; manager/Runner shutdown closes live contexts and invalidates handles without deleting those bytes. Normal Run completion is not profile cleanup. No backup, profile export/replay, retention sweeper or restoration of old live pages exists. Task/page close affects only the intended task resources, not all contexts or other Sessions.

Before the current fenced Runner first launches a Session context, it removes only
Chromium's transient `SingletonLock`, `SingletonSocket` and `SingletonCookie`
directory entries from the profile. An abruptly removed container can leave these
entries pointing to its former host and process. Unlinking the entries does not
follow their targets or delete cookies, authentication or other native site state.
The Session context lock and live context cache prevent this startup cleanup from
running against an already open context in the manager.

Task capacity is admitted before native context allocation, and page capacity before new page allocation. Failed registration closes the newly allocated page. Closing a task's final page retires its live identity and reclaims task capacity while retaining the Session context/profile.

Each context retains one internal blank tab so headed Chromium remains alive
after its final task tab closes. The blank tab is outside task/page projection
and task quotas, has no site navigation, and closes with the context.

The Runner application locks Patchright and Camoufox SDK dependencies. Image
provisioning installs matching Chromium and a pinned Camoufox/browser/fingerprint
model pairing, verifies the browser archive SHA-256, and supplies Xvfb and native
dependencies for displayless Linux execution. Runtime startup checks packaged
assets without downloading browsers, models or addons. Missing assets fail the
selected engine explicitly. System pip/Agent-installed drivers are not product
availability evidence. Both launchers preserve the trusted Runner proxy route,
including loopback destinations, without a direct-network alternative.

Required Runner host tests install both matching engines, model and native
prerequisites before pytest in CI; the product image does not supply the separate
host test environment. Browser-native and common contract tests exercise both SDK
boundaries; the representative product E2E covers browser-only switching,
source retirement, a new-engine page and preservation of the existing shell and
Runtime/Runner identity. Profile return and restart reconciliation stay in narrower
Runner and backend tests rather than expanding the E2E flow.

## Supported Observation and Interaction

Open allocates a Session task/page or opens a page in the supplied current task, applies optional navigation, and returns exact live resource identity. It does not claim navigation success merely because a page was allocated.

Observe reports task status or returns current page/frame DOM references, sanitized raw DOM, local readable Markdown glance, or image capture. DOM export preserves safe control structure/labels while omitting input values and unsafe attributes. Glance converts the selected current rendered DOM locally; it does not fetch an authenticated page remotely, invoke another LLM or automatically apply article extraction. Bounds/truncation and source scope remain observable. Detached/unsupported/offscreen content is not represented as complete.

Act performs structured navigation, observed-element input/select/check/key/scroll/hover/drag, scoped page closure, dialog responses, upload, waits and action-associated popup/download handling. Uploads require existing authorized Runtime files. Event expectation registration precedes the trigger. Download completion/failure is verified before returning the saved Runtime file. A captured PNG is not a site's downloaded document.

Navigation and URL waits honor the selected frame. Back/forward/reload, page closure and page dialog responses require the main-page target and reject subframe scope before effects.

Page dialogs have exact current identities. The Runner viewer application contract requires `input.source` explicitly: exact dialog responses require null, while pointer/key/composition input requires current acknowledged image metadata. A dialog before the first image or after navigation therefore remains answerable without fabricating frame identity. A pending dialog suspends the outstanding SDK operation's input-dispatch phase, permitting a scoped response without an operation-wide deadlock. Predetermined/observed responses and expected popup/download completion are reconciled; orphaned pending tasks/references are collected on scoped closure, cancellation and shutdown. Other Sessions can continue while one page dialog waits.

Each response races completion of the original operation against the next dialog. Consecutive dialogs retain that operation and release transient input arbitration at every handoff; cancelling a response drains its tracked original operation without replay.

## Actual Input Conflicts and Conversation Help

The manager's task-local transient interaction guard is the common final boundary for actual overlapping manipulation. It does not establish a persistent human/Agent ownership mode. Continuous composition/gestures can hold one actual interaction until end/cancel; a conflicting actor cannot insert input in the middle. Passive waiting and viewing do not acquire long-lived ownership. Viewer-requested navigate/back/forward/reload actions retain the originating attachment's actor identity through the common command handler and guard; the requesting attachment does not report its own navigation as another actor's conflict. Other viewers continue to observe and respect that transient ownership.

Help and continuation are ordinary Agent conversation/execution behavior: stop the affected manipulation, continue independent requested work if available, otherwise await normal user input; then freshly observe before continuing. There are no acquire/return tools, first-input takeover, help registry, string-keyword ownership protocol or whole-Run interruption. Panel/browser attachment functionality is separate from this Agent command implementation.

## Captures and Existing Delivery

Image observation saves an original native-density PNG in the current Session working context, with exact size/dimensions and bounded capture limits. Full-page capture checks its sixteen-million-pixel limit against device-pixel area (CSS width × height × device scale squared) before native screenshot execution. Live frames and intentional captures preserve native website rendering, including the site's own password bullets; no credential/password/one-time-code masking layer is added. Model normalization never overwrites the original.

The Engine uses the existing RuntimeImageReadService and ModelFile-backed FilePart to return actual model-visible image input. A path alone, missing transfer service, oversized image or failed materialization is not successful image observation. The Agent can explicitly invoke existing `present_file` to publish the original through verified Exchange transfer; this command layer does not claim user publication merely because capture succeeded.

Raw page/input data, profile bytes and full sensitive URLs are not copied to generic errors/logs. Observation and original files are intentional content delivery, not continuous live-frame recording.

## Support-Dependent Native Sandbox

Initialization probes native sandbox startup using a blank browser under the current product engine/user/Runtime policy. A successful probe selects sandbox-enabled contexts. Only specifically recognized native sandbox incompatibility selects sandbox-disabled contexts; the unsupported branch is explicitly functional, not equivalent exploit isolation. A missing binary, unrelated startup failure or timeout does not trigger that downgrade. The disabled branch also verifies that the product engine can launch.

The assessment is local to the current manager environment and is re-established after replacement. No user sandbox setting, durable compatibility registry, privileged container change or kernel/AppArmor/seccomp mutation is created. Existing Runtime network and Session/task authority remain applicable in both branches.

## Verification Boundaries

The confidential-input Engine E2E provisions account/password entries through
public settings, imports the actual projected Skill script and executes separate
Runtime-side encryption commands before native fills. A controlled site verifies
a combined hash, and Session history plus Worker/Public/Control logs are scanned
for plaintext. The same isolated test Runtime is restarted through the public
API; old ciphertext fails on a fresh target without a site input event, and fresh
commands supply new ciphertext that succeeds. Narrow tests cover malformed
input, native SDK failure sanitization, stale-reference ordering and process-key
manager reuse. These synthetic checks do not establish real-account or
production deployment acceptance.

Shared strict DTO/codec, current generations/targets, native Session state, dialog/event/file combinations, observations/capture bounds and transient conflict behavior have focused unit/real-SDK coverage. Engine tests cover full catalog/provider schema lowering, access revocation, current working-folder binding, mandatory action-state/result scope and image failure propagation.

Focused tests and static component stories do not establish assembled-product acceptance. The representative Browser E2E uses normal user creation/login, an Engine-created task, real Runner images and API/Control source admission, a read-only child and unrelated-user denial, native pointer/dialog/composition input, fresh reconnect and the real Web panel. A separate normal-authentication Engine journey verifies actual model imagery, original Runtime PNG identity and authorized Exchange publication/download. The [delivery verification report](../../design/session-browser-verification-report-2026-10-15.md) records completed checks, historical failures and evidence limits. Real iPhone Safari, OS-mobile IME, production deployment and real-site acceptance are not established by these synthetic journeys.
