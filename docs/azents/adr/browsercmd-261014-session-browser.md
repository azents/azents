---
title: "Session Browser Runtime Command Decisions"
created: 2026-10-14
tags: [browser, session, runtime, architecture, security]
document_role: primary
document_type: adr
snapshot_id: browsercmd-261014
---

# Session Browser Runtime Command Decisions

- Snapshot: `browsercmd-261014`
- Document reference: `browsercmd-261014/ADR`
- Requirements: [browsercmd-261014/REQ](../requirements/browsercmd-261014-session-browser.md).
- Mode: Collaborative. The requester owns remaining material decisions.

## Prior Authority and Replacement Boundary

This snapshot records the approved replacement for the withdrawn MCP integration. The previous [browser-261014/ADR](browser-261014-session-browser.md) remains historical evidence; its D3 approval withdrawal is preserved.

The following requester-approved boundaries are carried forward unchanged:

- `browser-261014/ADR-D1`: shared Runtime HTTP/WebSocket transport beneath separate Web and Browser admission domains; no public browser Web service or raw debugging ingress.
- `browser-261014/ADR-D2`: Runner-owned live browser manager and Session/task/page registry; native state follows existing Runtime storage, independently of live handles.
- `browser-261014/ADR-D4`: Runner-authoritative task writer state and final Agent/human input admission; Control validates existing access and UI displays projections.

These authorities apply to the preserved outcome identifiers in `browsercmd-261014/REQ`. Prior D4 establishes the Runner's live admission boundary; D2 below resolves its scope as actual interaction-conflict admission, without a persistent human-control grant. Complete Design approval remains separate.

## Current-System Evidence

The existing `runtime_runner_control.proto` carries Runner operation requests, start acknowledgement, cancellation, and operation result events on the authenticated outbound Runner Control connection. `RunnerOperations.handle` decodes operation-specific typed payloads before handler dispatch. There are no product browser operation handlers at this baseline.

Existing generic operation execution is evidence for a bounded command path, not authority to inherit shell-process expiry or quotas as browser-manager retention. Existing file transfer and model image materialization remain separate from live viewer transport.

## Material-Decision Map

| Topic | State | Owner |
| --- | --- | --- |
| Transport foundation and Browser admission | Carried forward: prior D1 | Requester |
| Browser resource/lifecycle owner | Carried forward: prior D2 | Requester |
| Task writer source of truth | Carried forward: prior D4 | Requester |
| Agent automation contract and execution path | Accepted: D1 below | Requester |
| Help/continuation and actual interaction-conflict admission | Accepted: D2 below | Requester |
| Raw DOM/glance and image/file integration | Required by REQ-10/REQ-11 and D1; current-page extraction and existing delivery boundaries fixed | Agent for equivalent local converter/helpers; requester for any new service or behavior |
| Built-in browser usage Skill delivery | Accepted: D3 below, existing managed release path | Requester |
| Native browser sandbox and unsupported-Runtime availability | Accepted: D4 below; use sandbox only where supported, not an availability prerequisite | Requester |

## D1. Use Three Typed Browser Tools over Runtime Commands and Playwright SDK

- Decision reference: `browsercmd-261014/ADR-D1`
- Accepted by the requester on: 2026-10-14 at 19:38 KST
- Affected requirements: `browsercmd-261014/REQ-1` through `REQ-12`.
- Approval scope: the bounded public tool roles, Runtime command execution path, and supported capability categories described below. Exact schemas and complete Design approval are not implied.

### Decision

Implement three supported Agent browser tool roles through the existing Runtime command path to Runner-owned handlers. Use the Playwright SDK in the Runner to perform actual browser automation, preserving current resource and task writer authority.

The proposed names are `browser_open`, `browser_observe`, and `browser_act`; exact identifiers are local implementation details. The accepted roles are:

- **Open:** allocate/open the current Session's browser task/page, reuse its native site state, return concrete resource identifiers, and provide linkage to the existing browser side panel.
- **Observe:** report task-owned pages/current state and provide actionable DOM/reference observation, needed raw DOM access, concise rendered-page text/Markdown, actual Agent image observation, and intentional original capture-file saving.
- **Act:** execute structured navigation/input/page closure, task/page/frame-targeted interaction, page dialog responses, authorized upload/download, and condition/event waits. Register an expected popup/download before its triggering action rather than relying on a separate later wait call to recover a missed event.

Calls derive trusted Session authority from execution context and bind concrete task/page/frame targets as applicable. They do not share a Runtime-global ambient selected page. The existing task arbiter admits supported Agent and human inputs; tool schemas and usage guidance cannot replace final admission.

Do not add MCP server/client/relay integration as the execution layer. Do not delegate the browser-manager lifetime to Agent-installed commands or launch a new browser for each call. Browser manager resources persist across command calls under the already-approved lifecycle.

Live human viewer traffic remains on the separately admitted D1 common data plane. Saved capture/file delivery uses existing file-transfer and image-materialization facilities; ordinary browser command envelopes are not a replacement live video transport.

### Included and Unapproved Scope

Supported capability categories are those listed above, not the entire Playwright SDK. Basic observed-element input and task/page/frame, dialog, file, and condition/event handling must have explicit typed contracts.

Hover/drag/coordinate input can extend the same Act role when the supported workflow requires it; the requester did not require universal canvas/map interaction. Arbitrary Agent-supplied JavaScript, network interception, tracing, and general browser/context configuration are not required by this decision and are not automatically exposed. Fixed implementation-owned DOM extraction is distinct from exposing a generic code-execution tool.

The existing `read_image` and `present_file` paths are accepted integration reuse targets for actual model imagery and ordinary user attachments, subject to file authority and original-capture preservation. This does not create a new capture store or continuous-frame log.

### Rationale

Runtime commands already provide the product's authenticated request/cancellation/result path. Using that path with Playwright SDK avoids an additional local MCP execution and protocol integration boundary while still reusing the browser automation engine and its actionability/auto-wait behavior.

Keeping three public roles does not imply three tiny operations: Azents owns the typed action/target/event/result/error contract. Browser-specific auto-wait, events, dialogs, file handling, and stale state therefore need explicit design and tests.

### Alternatives Not Selected

- MCP server integration: the requester withdrew it because of local execution/relay and communication complexity.
- A minimal three-tool surface containing only simple open/read/click operations: insufficient for the approved multi-page/dialog/file/event workflows.
- An unrestricted script-based Playwright surface: broader execution authority and lifetime obligations, not approved.

### Consequences and Feasibility Gates

- Define and validate browser-specific typed ingress, cancellation, exact current resource binding, errors, and bounded results against current Runner command scheduling.
- Distinguish operation completion, expected browser outcome, and uncertainty. Do not replay a submission after interrupted delivery.
- Verify Session state separation/reuse and task-only page/frame/popup targeting and closure.
- Verify dialogs, upload file authority, pre-armed download/popup expectations, file completion, and delivery failure.
- Verify that waiting and browser failures do not block unrelated Runner operations or tasks; generic exec limits do not establish browser lifetime.
- Validate DOM/text extraction on representative rendered application pages, actual model image input, and original screenshot export.
- Settle the remaining material writer transitions and extraction choices, then write and approve the complete Design before implementation.

## Removal and Existing-State Boundary

No product browser feature or MCP installation exists at the research baseline. The replacement concerns unimplemented design authority; it does not authorize deleting prototype/profile data or changing existing Web, Terminal, file-transfer, or Session access behavior. The final Design must analyze actual extraction/removal obligations for the shared transport work.

## D2. Use Conversation for Help and Limit Runner Arbitration to Actual Input Conflicts

- Decision reference: `browsercmd-261014/ADR-D2`
- Accepted by the requester on: 2026-10-14 at 19:59 KST
- Affected requirements: `browsercmd-261014/REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`.
- Approval scope: help/continuation semantics and the minimum admission boundary. The previously proposed first-input takeover and persistent human-controlled writer mode were never accepted and are excluded.

### Decision

Use ordinary conversation and existing execution behavior for browser help and continuation. The Agent stops manipulating the affected task when asking for help, performs independent requested work if available, and otherwise waits for ordinary user input. A continuation message provides context; the Agent freshly observes the actual page before further action.

The Runner remains the final task-local input-admission owner. Its supported Agent/human paths prevent actual overlapping manipulation and reject unauthorized, disconnected, or stale-resource input. This short-lived execution/interaction arbitration is not a persistent actor-owned help/control mode.

Do not create a human-control flag, acquire/return command, first-input takeover lifecycle, or ownership-reclaim step for the Agent. A help request, browser view, human interaction, or completed interaction does not by itself install a continuing block on subsequent Agent actions. Do not reject an Agent action merely because the task previously needed human help.

Actual contention and stale/current authority failures can still prevent an action and provide their reason. Competing input is not held for later automatic replay. Avoid interleaving another actor's input with an active manipulation or continuous input interaction, including composition/gesture handling. Preserve uncertainty when already-started input cannot be confirmed or undone; switching actors does not imply cancellation or rollback of a submitted action.

Browser viewing and conflict admission do not forcibly stop the whole Agent Run or block unrelated tasks. Panel closure or connection loss does not signal successful help or automatic Agent resumption. No keyword-parsing handback subsystem or new asynchronous Agent-interruption event is introduced.

### Rationale

The confirmed primary workflow already stops affected browser manipulation before human help and resumes through normal conversation. A persistent human-owned writer grant adds a second help lifecycle with no required user outcome. Actual overlapping input and stale requests still need authoritative Runner checks under prior D4 and the existing generation/resource boundaries.

### Alternatives Not Selected

- Persistent human-control mode that rejects future Agent actions until a grant is returned: unnecessary for the accepted workflow.
- Automatic takeover on the first human input while an Agent continues working: adds an unrequested takeover workflow and transition semantics.
- Relying only on the Agent's intended pause without final conflict/stale-input checks: does not satisfy the concurrent-input and current-resource requirements.

### Consequences and Validation Obligations

- Verify help/continuation through ordinary conversation without acquire/return tools, human-control UI, or a task-wide help lock.
- Verify that viewing and a previously completed human interaction do not leave a lasting block on valid Agent actions.
- Verify actual Agent/human and human/human collision rejection, continuous-input boundaries, current-resource identity, and disconnected/stale input.
- Verify ordinary continuation with fresh observation, independent work, and no automatic replay or successful-login assumption.
- Keep cancellation, browser-resource lifetime, and existing Session access separate from help state. Exact local synchronization structures and typed conflict outcomes belong in Design.

## D3. Deliver One Built-in Browser Skill through Existing Managed Skill Facilities

- Decision reference: `browsercmd-261014/ADR-D3`
- Accepted by the requester on: 2026-10-14 at 20:15 KST
- Affected requirements: `browsercmd-261014/REQ-6`, `REQ-10`, `REQ-11`, `REQ-12`, `REQ-13`.

### Decision

Include one default browser usage Skill and focused API references in the existing approved global managed Skill release bundle. Use the current `azents` namespace, immutable per-Run VFS projection, discovery and `load_skill` path documented in [Toolkit](../spec/domain/toolkit.md#managed-skill-vfs). Do not add another distribution system, dynamic code installer, or browser-specific capability-grant mechanism.

Guide the supported three tool roles and their current-target observation/action/result discipline, ordinary-conversation help/resume, actual conflict and stale-state handling, image/capture/file delivery, and untrusted page content. Check tool availability rather than promising browser functionality to an Agent without a usable Runtime.

The Skill is instructional content. Runner and service access/input admission remain authoritative. It does not add persistent human control, acquire/return commands, automatic input retry, raw CDP, or an unrestricted JavaScript path.

### Rationale and Validation

The managed release/VFS path already supplies discoverable default guidance with exact per-Run content identity. Reusing it avoids adding installation or lifecycle machinery to the Runtime. Verify release scanning, projection/discovery/load behavior, tool-reference consistency, unavailable-browser guidance, and ordinary help/capture examples against the final supported schemas.

### Alternative Not Selected

Relying only on tool descriptions without default browser workflow guidance does not satisfy the newly confirmed REQ-13. Tool descriptions still carry the immediate input/output contract.

## D4 Candidate Brief: Native Browser Sandbox Availability

The synthetic SDK experiment found that native Chromium sandbox startup fails under the current non-root Runtime with `No usable sandbox!`. Functional checks ran without the native sandbox only as an isolated synthetic experiment. This does not prove the exact target product image's configuration or authorize a production workaround.

Question: must supported browser startup require a usable native Chromium sandbox, or may it run without that sandbox while relying on the existing Runtime containment?

- **Candidate A: Require the native sandbox.** An incompatible Runtime reports browser unavailable with a concrete reason; no automatic no-sandbox fallback. Restoring support may need a compatible image/Runtime policy, investigated separately and changed only with explicit infrastructure authority. This improves page-exploit containment but may leave the current Runtime unable to provide the feature.
- **Candidate B: Permit sandbox-disabled Chromium inside existing Runtime containment.** Avoids requiring native sandbox availability in that environment, but a compromised browser renderer has a weaker internal boundary against Runtime files and other Session state. Session/profile mapping remains functional separation, not exploit containment.

Recommend A as the product security baseline, subject to requester choice. Do not claim separate profiles or Runner command authorization replace a native browser sandbox. No privileged container, kernel/AppArmor/seccomp modification or infrastructure execution is authorized by this candidate brief. A choice must update applicable Requirements/ADR/Design authority before final approval; it is currently unaccepted.

## D4. Use Native Browser Sandbox Only Where the Runtime Supports It

- Decision reference: `browsercmd-261014/ADR-D4`
- Accepted by the requester on: 2026-10-14 at 21:12 KST
- Affected requirements: `browsercmd-261014/REQ-14`, with existing access, state and lifecycle constraints unchanged.

### Decision

Enable the native Chromium sandbox when it is supported by the current product browser/Runtime environment. Native sandbox support is not mandatory: when it is specifically unavailable, launch the product browser without native sandboxing under the existing Runtime containment and network/access policy.

Establish support from trusted product provisioning/runtime capability evidence or an isolated blank-browser startup probe in the same current environment. A successful sandbox-enabled start establishes support. Only a specifically identified native sandbox incompatibility establishes the unsupported branch. A generic browser exit, missing binary, package error, timeout, resource exhaustion or navigation failure is not permission to disable sandboxing.

Keep the support assessment associated with the current Runtime/Runner/browser environment; re-establish it after replacement or relevant provisioning change. This is bounded local initialization evidence, not a durable capability registry, user-controlled mode or new configuration system. Do not mutate existing Session profiles or start an authenticated page merely to probe support.

Do not change privileges, seccomp/AppArmor/user-namespace policy, kernel settings, container configuration or infrastructure automatically. Other browser failures retain their ordinary unavailable/error classification. This conditional sandbox policy does not relax current Session/task authority, actual conflict checks, native-state separation or network restrictions.

### Rationale and Risk

The requester chose compatibility with otherwise supported Runtimes while retaining native sandbox protection wherever available. Sandbox-disabled rendering has a weaker boundary against exploit access within that Runtime; Session profile mapping does not replace that boundary. This is an explicitly accepted trade-off, not a claim that the unsupported branch has equivalent isolation.

### Alternatives Not Selected

- Requiring native sandbox support and disabling the feature on incompatible Runtimes: not the requested availability policy.
- Always disabling native sandboxing: discards protection in environments that support it.
- Treating every startup failure as sandbox incompatibility: hides unrelated errors and can silently weaken protection.

### Validation Obligations

- Exercise a supported sandbox-enabled start and a specifically unsupported native-sandbox start path with current environment evidence.
- Verify that unrelated installation/startup/timeout failures do not select the unsupported branch.
- Verify current resource/generation binding, no profile alteration by probing, and no privilege or infrastructure changes.
- Retain bounded non-secret support reason/selected launch protection in diagnostics without copying raw launch/environment/page content.

The preceding D4 candidate brief remains historical comparison context; this accepted decision records the requester's selected support-dependent policy.
