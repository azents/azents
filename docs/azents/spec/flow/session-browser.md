---
title: "Session Browser Execution"
created: 2026-10-15
tags: [browser, session, runtime, engine, security]
spec_type: flow
owner: "@Hardtack"
touches_domains: [agent, session, toolkit, runtime]
code_paths:
  - python/libs/azents-runtime-control/src/azents_runtime_control/browser_contract.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/browser.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/operations.py
  - python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py
  - python/apps/azents-runtime-runner/pyproject.toml
  - python/apps/azents-runtime-runner/Dockerfile
  - python/apps/azents/src/azents/engine/tools/browser.py
  - python/apps/azents/src/azents/engine/tools/builtin.py
  - python/apps/azents/src/azents/engine/tools/runtime_io.py
  - python/apps/azents/src/azents/runtime/control_protocol/runner_operations.py
  - python/apps/azents/src/azents/runtime/runner_operation_adapter.py
last_verified_at: 2026-10-15
spec_version: 1
---

# Session Browser Execution

## Reachable Scope

The Agent has three Runtime-backed browser tool roles: `browser_open`, `browser_observe`, and `browser_act`. They execute through the existing authenticated Runner operation path, not an MCP server or Agent-installed CLI. This implementation provides Agent automation and observation; Browser public attachment routes, a human viewer and default browser Skill are not activated by these command handlers alone.

Browser tools require a current managed Runtime and concrete Session/Run resource authority. Runtime capability guards enforce process/workspace availability, and image observation additionally requires current transfer authority. Projection without current execution authority omits these tools. Each call revalidates access and resolves its actual Session working folder independently of any scheduling/root alias.

## Typed Command and Result Boundary

The shared runtime-control library declares frozen operation-specific Browser DTOs and strict codecs. Model-facing schemas have one top-level object. The Engine sends normalized typed commands through `browser.open`, `browser.observe`, `browser.act`, or an internal `browser.list` projection; the latter is not a fourth model tool. Decoding rejects malformed primitive types, missing mandatory fields, unknown fields, unsupported operations and invalid action combinations before effects.

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

Page dialogs have exact current identities. A pending dialog suspends the outstanding SDK operation's input-dispatch phase, permitting a scoped response without an operation-wide deadlock. Predetermined/observed responses and expected popup/download completion are reconciled; orphaned pending tasks/references are collected on scoped closure, cancellation and shutdown. Other Sessions can continue while one page dialog waits.

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

Actual public Session viewer, authenticated transport, mobile/IME and original user publication E2E are not established by these focused command tests. Combined product acceptance uses the real built Runner and normal Engine/access/file/stream surfaces; the implementation Design remains unimplemented until that complete verification is finished.
