---
title: "Session Browser Observation and Input Decisions"
created: 2026-10-14
updated: 2026-10-14
tags: [browser, session, runtime, architecture, security]
document_role: primary
document_type: adr
snapshot_id: browser-261014
---

# Session Browser Observation and Input Decisions

- Snapshot: `browser-261014`
- Document reference: `browser-261014/ADR`
- Requirements authority: [browser-261014/REQ](../requirements/browser-261014-session-browser.md), requester-confirmed on 2026-10-14.
- Mode: Collaborative. The requester owns material technical decisions.
- Accepted decisions are recorded below with exact scope. Candidate briefs and unresolved topics are not implementation authority.

## Current System and Gaps

Research baseline: `fdb34e87d`.

### Session UI and authority

`SessionSidePanelPresentation` and the `sessionPanel` navigation support the existing desktop/mobile panel, but no browser destination exists. `authorize_public_session_resource` checks the concrete Session, its root where applicable, Workspace membership, and USER ownership. Public input admission rejects subagent write targets. These are existing authorities, not a new browser read/write role system. Browser input must not silently grant authority to a currently read-only Session.

### Runtime data plane

[Agent Runtime Control](../spec/flow/agent-runtime-control.md) describes the existing outbound Runner channel and the separate multiplexed Web data plane with exact Runtime/Runner generations and Owner epochs. Browser imagery and input must not be treated as ordinary durable chat/tool payloads.

The current Runtime Web feature is an Agent-and-port application service with a stable hostname, a finite On deadline, human activation, and service revision. Its Gateway authority does not bind a product Session or browser task and does not distinguish observation from interactive input. Platform identity cookies are stripped before application forwarding. Application URLs, query parameters, Origin, and client-supplied headers cannot establish trusted Session ownership.

Reusing the Web **transport** is distinct from registering the browser as a general Runtime Web **service**. The approved browser flow does not authorize an On/Off exposure workflow, a finite public service window, or a new raw debugging endpoint for each browser Session.

### Browser execution

The Runner currently installs the Python Playwright package and Chromium system dependencies, but has no browser-specific Runtime capability, browser-management protocol, or installed Chromium binary contract. Tools independently installed by an Agent are not existing product dependencies or implementation candidates.

Generic managed execution uses Session-owned process cancellation and idle/lifetime/quota cleanup. A browser manager cannot silently inherit those limits as a new browser-state retention policy. [Agent Runtime Persistence](../spec/flow/agent-runtime-persistence.md) already defines provider-owned Workspace durability and normal start/stop/restart behavior. The requirement is natural Session-state reuse within existing storage authority, not a new backup/restore subsystem or exact live-page reconstruction.

### Input ownership

Existing Runtime generation fences do not provide browser task/page identity or a competing Agent/person writer fence. The supported browser surface must reject stale task input and serialize input for the affected task without introducing a human-help request lifecycle.

## Fixed and Derived Outcomes

- Reuse the existing Session side panel; do not add a top-level browser page.
- Preserve current Session/Agent access, including private USER Sessions and read-only public subagent write targets.
- Separate browser task presentation and login/site state by Session; input contention is task-local.
- Request help and continue through ordinary conversation; no request registry, expiry, or required return button.
- Follow existing Runtime storage lifecycle without deliberate state deletion on normal stop/start or an additional persistence subsystem.
- Keep installed Agent tools outside product authority and dependency decisions.
- Keep Runtime transport outbound and authenticated; do not expose raw browser debugging or create a new unauthenticated Runtime ingress.
- Current access and task identity remain required after reconnection; uncertain page actions must not be replayed.

## Pending Material-Decision Map

| Topic | State | Decision owner | Consequence |
| --- | --- | --- | --- |
| Trusted Session browser admission and data transport | Accepted: D1 | Requester | Generalize the shared Runtime HTTP/WebSocket data plane; Web and Browser keep separate domain admission authorities above it. |
| Product browser-resource ownership | Accepted: D2 | Requester | The Runner owns live browser allocation and the authoritative Session/task/tab registry; native state follows existing Runtime storage. |
| Agent browser-action contract | D3 approval withdrawn; replacement pending | Requester | MCP integration is no longer authorized. A fixed tool surface implemented through Runtime commands is under discussion. |
| Task-local writer ownership and stale-input fencing | Source of truth accepted: D4; acquisition/release pending | Requester | The Runner owns current task writer admission; exact competing-input and attachment transitions remain unresolved. |
| Supported action capabilities and script execution scope | Pending | Requester where material | Exact supported operations must preserve task authority; unrestricted code execution is not approved. |

Product-scope follow-up: REQ-10/REQ-11 updated criteria and the built-in usage Skill proposal still require consolidated confirmation. The already-confirmed REQ-1 through REQ-9 support D3's bounded automation-foundation decision.

Natural state reuse is a fixed requirement, not a separate retention decision. File names, equivalent local helpers, identifiers, and fixture composition remain agent-owned unless they create new state, behavior, authority, or operational modes. Material choices discovered by further system framing will be disclosed before being accepted.

## D1 Candidate Brief: Trusted Admission and Transport

Question: once current Session/task observation or input authority is established, which Runtime data-plane boundary should carry browser frames and commands?

### Candidate A: Dedicated admission, existing Web transport

Add a trusted Session/task-bound browser admission path and a distinct browser-purpose authority to the existing multiplexed Runtime Web transport. Retain the transport's authenticated outbound Runner connection, flow control, cross-replica Owner routing, and generation fences. Do not use a public Runtime Web service ID, On deadline, application cookie, or untrusted Session query as browser authorization.

Benefits:

- Reuses existing transport routing and flow-control mechanisms rather than building another data plane.
- Keeps browser local HTTP/WebSocket forwarding behind the existing outbound Runtime boundary.

Costs and conditions:

- Current stream authority is service-specific; a distinct browser-purpose authority requires explicit protocol and validation changes throughout the affected accepting Control, Owner, and Runner path.
- Generic Web service admission must remain unchanged. Regression evidence must prove browser authority cannot authorize ordinary service access or bypass browser Session/task checks.
- The browser control contract remains a separate decision; reuse of generic bytes does not supply task writer ownership.

### Candidate B: Dedicated browser data stream

Use a dedicated authenticated browser data protocol and Runner RPC/attachment, following the existing Terminal pattern for a separately scoped interactive resource. Reuse current control authentication, Runtime lifecycle evidence, and Session authorization without borrowing Terminal-only policy flags or public Web exposure state.

Benefits:

- Browser Session/task admission and frame/input semantics are explicit, separate from generic application service exposure.
- Less change to existing public Runtime Web service behavior and authority.

Costs and conditions:

- Adds browser-specific stream registration, flow control, Owner routing, lifecycle coordination, and tests rather than reusing the current multiplexed Web path end to end.
- Terminal code is evidence of an existing pattern, not authority to copy its policy, replay, persistence, quotas, or deadlines unchanged.

### Initial recommendation, subsequently refined

Recommend Candidate A if the browser-purpose authority can be separated completely from general Runtime Web service admission. This recommendation is conditional on exact, system-grounded authority and regression evidence; transport reuse must not create user-visible On/Off steps or weaken Session access. If that boundary cannot be implemented coherently, return the conflict and revised options before acceptance.

The requester asked whether generalization was possible rather than direct Web transport reuse. The accepted refinement is recorded as D1 below. The initial candidates are comparison context, not separate accepted mechanisms.

## D1. Generalize the Runtime HTTP/WebSocket Transport Below Web and Browser

- Decision reference: `browser-261014/ADR-D1`
- Accepted by the requester on: 2026-10-14
- Affected requirements: `browser-261014/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`, `REQ-8`, `REQ-9`, and the fixed existing-access/Runtime-boundary constraints.

### Decision

Extract and generalize the existing Runtime HTTP/WebSocket data-plane foundation. Runtime Web and Session Browser are sibling domain consumers of that foundation; Browser is not a special case inside Runtime Web.

The shared foundation owns authenticated outbound Runner connectivity, exact Runtime/Runner generation and Owner epoch fencing, Control-to-Owner routing, multiplexed streams, backpressure/flow control, and transport termination. It does not decide Web On state, service exposure, browser Session ownership, task ownership, or permission to observe versus manipulate a browser.

Web retains its existing service-ID, revision, identity, finite On/exposure, and admission behavior in its own domain entry point. Browser validates concrete Session/task and observation/input authority in a separate entry point before forwarding through the common transport. Do not register the browser as a public Runtime Web service or apply Web exposure deadlines to its product lifetime.

Define explicit domain-specific Web and Browser connection authorities rather than growing the current Web service authority with nullable Session/task fields. A Web authority cannot authorize Browser and a Browser authority cannot authorize general Web service access. The common transport only accepts an appropriately admitted domain connection; authority checks and live revocation remain obligations, not merely a UI convention.

Generalization is bounded to local Runtime HTTP/WebSocket forwarding needed by Web and Browser. Do not merge Terminal, file-transfer, all Runtime operations, or all RPC protocols in this snapshot, and do not add a generic plugin framework or new user-visible configuration solely to generalize the transport.

### Rationale

Current `runtime_stream_session.proto` already names common transport sessions and envelopes; `runtime_stream_flow.py` provides `AbsoluteCreditWindow`, `HierarchicalCredit`, and `FairFrameScheduler` independent of browser/task meaning. The current stream authority and dispatch remain Web-service-specific (`service_id`, `service_revision`, exposure deadline, and Web capacity/routing types), so extraction must change real responsibility boundaries rather than rename classes or bolt on Browser branches.

This direction avoids coupling Browser to application-service exposure while also avoiding a duplicated browser-specific data plane. Existing generic Web behavior remains unchanged at its domain boundary.

### Alternatives Not Selected

- Directly extending Runtime Web as the Browser parent: leaves Web-service semantics at the browser admission boundary and encourages optional-field or feature-branch coupling.
- A separate browser data-plane RPC and coordination path: cleanly isolates Browser but duplicates transport routing, flow-control, and connection machinery that can sit beneath both domains.
- Generalizing all Terminal/transfer/control protocols together: expands the snapshot beyond the two concrete HTTP/WebSocket consumers and their approved requirements.

### Consequences and Validation Obligations

- Public Web service configuration, On/Off behavior, authentication, and exposure duration remain authoritative and must have regression coverage after extraction.
- Existing transport fingerprints and generation fences must remain exact; this decision does not authorize fallback or user-visible protocol version management.
- Reject wrong authority variants, cross-Session/task identities, stale generations, revoked access, and requests that were not admitted by the correct domain entry point.
- Verify shared connection/buffering/capacity behavior so Browser traffic cannot silently bypass or weaken Web transport protections. Concrete capacity allocation policy remains subject to system-grounded Design and any material decision it exposes.
- Trace extraction/removal of Web-specific responsibilities from the common path and their replacement in the Web adapter, including current route/coordination/state and generated protocol surfaces. Do not silently migrate or duplicate durable authority.
- This decision establishes transport structure only. Browser resource ownership, Agent automation interfaces, task writer fencing, and lifecycle behavior are not decided by D1.

## Removal and Existing-State Boundaries

There is no production browser feature to migrate at the research baseline. Existing side-panel, Session authorization, ordinary conversation, and generic Runtime Web service semantics must remain authoritative. Prototype browser state and Agent-installed tools are outside this snapshot's removal scope. A complete repository-grounded removal and absence-verification analysis belongs in the implementation Design after the remaining decisions are accepted.

## D2 Candidate Brief: Runtime Browser-Resource Ownership

Question: should live browser processes and Session/task/tab ownership be managed by the Runner itself, or by a separately supervised product browser service inside the same Runtime?

Both candidates require a product-owned browser engine installation and lifecycle contract; current Agent-installed binaries are not dependencies or candidates. Both keep native browser state under existing Runtime storage authority without backup, explicit storage-state replay, or a new retention subsystem. A browser process is distinct from its saved profile state. Neither candidate guarantees continuation of live page/input state after Runtime replacement.

### Candidate A: Runner-Owned Browser Manager

The Runner owns browser allocation, native per-Session state association, task/tab identity, local observation/input endpoint lifetime, and resource cleanup. Native browser engines may remain child processes; the manager and authoritative live resource registry are owned by the Runner, not by ordinary Agent shell execution.

Benefits:

- Current Runtime/Runner generation authority can govern the live browser resource registry directly.
- Uses the product's existing lifecycle owner rather than introducing another service supervisor and registration protocol.
- Browser status and termination can distinguish Runtime invalidation from a normal conversation ending, without adopting generic exec process TTL/cancellation as browser retention semantics.

Costs and conditions:

- Adds browser initialization, native dependency installation, resource limits, and cleanup responsibilities to the Runner.
- Browser-manager failure isolation from other Runner operations must be designed and tested.
- Runner/control reconnect behavior must be explicit; saved profile state may remain while live attachments are invalidated. Do not treat connection recovery as a live-page restoration feature.

### Candidate B: Independently Supervised Product Browser Service

A separate product-provided process inside the Runtime owns the browser resource registry and native browser processes. The Runner transports admitted browser connections and reconciles its generation-bound association with that service. This is a product service, not a user/Agent-installed browser tool or general public Runtime Web service.

Benefits:

- Separates browser driver dependencies and manager failures from the Runner's main process.
- The service can remain independent of a particular Runner control connection while physical Runtime compute remains present.

Costs and conditions:

- Requires its own supervision, startup/readiness, shutdown, resource registry, exact Runner-generation binding, and orphan/stale resource handling.
- Does not eliminate Runtime restart behavior or authorize a second durable lifecycle source of truth.
- An independent local service must not accept untrusted task identities or raw public debugging connections.

### Recommendation and Acceptance

Recommend Candidate A for the current scope: live browser resources belong to the existing Runner lifecycle owner, while native profile bytes follow ordinary Runtime storage. Do not introduce a separately supervised product daemon merely for state preservation.

The requester selected Candidate A. Accepted scope is recorded below; Agent action and writer contracts remain separate decisions.

## D2. Make the Runner the Owner of Live Browser Resources

- Decision reference: `browser-261014/ADR-D2`
- Accepted by the requester on: 2026-10-14
- Affected requirements: `browser-261014/REQ-2`, `REQ-3`, `REQ-5`, `REQ-8`, `REQ-9`, and existing Runtime lifecycle/storage constraints.

### Decision

The Runner owns the browser manager and the authoritative live association of concrete Session, browser task, and tab resources. It owns allocation, native browser process attachment, local observation/input endpoint lifetime, and teardown. Native browser engines can be child processes; this is not a requirement to run browser engine internals inside the Runner process.

Do not introduce an independently supervised product browser-manager service, delegate resource ownership to an Agent-installed tool, or model the browser manager as an ordinary managed shell execution. Existing generic exec cancellation, idle expiration, and process quotas do not silently define browser-manager lifetime.

Associate Session-specific native browser state with existing Runtime storage. Normal conversation completion or Runtime stop/start must not deliberately delete that state. No browser-specific backup, storage-state export/replay, restore registry, retention scheduler, or new state-reset UI is authorized. Site expiry and loss of live page/input state remain possible.

Current Runtime/Runner generation authority fences the manager's live resource registry and attachments. Saveable native state and live resource identity are different: retaining a profile does not keep an old page handle or authorize stale input after Runner/Runtime replacement.

### Rationale

The Runner is the existing owner of local Runtime execution and generation-bound operations. Keeping the browser resource owner there avoids a second service supervisor, registration protocol, and lifecycle source of truth. Product browser installation, resource limits, cleanup, and error containment are still explicit obligations and cannot be supplied by tools an Agent happened to install.

### Alternative Not Selected

A separately supervised browser-manager service inside the Runtime offers process failure isolation, but introduces readiness, startup/shutdown, orphan registry, and exact-generation reconciliation work beyond the current resource-owner need. Native browser child processes can provide execution separation without a second authoritative product manager.

### Consequences and Validation Obligations

- Define the manager's exact current Session/task/tab identities, invalidation boundaries, process ownership, and failure isolation from other Runner capabilities in the Design.
- Distinguish ordinary conversation completion, user cancellation, Runner connection loss, browser engine exit, and physical Runtime lifecycle without adding a human-help or retention workflow.
- Test Session A/B native site-state separation, same-Session reuse, task-local tab closure, and stale handles after manager/browser/Runner replacement.
- Install and validate the required product browser engine through product-owned Runtime provisioning; Agent-installed tools remain outside this dependency contract.
- Preserve current Runner-reported Workspace path authority and existing destructive storage boundaries; this decision does not authorize Session purge/archive migrations or additional cleanup policies.
- Agent automation entry points and competing writer ownership are not selected by D2.

## D3 Candidate Brief: Supported Agent Automation Entry Point

Question: should the product integrate a known browser tool contract/executor under its own resource and authority adapter, or expose a broader script/automation protocol surface?

The previous custom three-tool `open/observe/act` proposal did not establish adequate Playwright coverage and is no longer the recommended starting point. Combining functions into three names does not eliminate the cost of maintaining locators, frames, events, tabs, dialogs, downloads, and execution semantics.

### Revised Recommended Proposal: Playwright MCP Contract and Executor with an Azents Adapter

Use the Microsoft Playwright MCP tool surface and automation execution as the primary integration candidate, rather than inventing an Azents browser action API. Supply the Runner-owned browser and preserve D2 resource ownership; the MCP executor is a scoped execution component, not an independent browser manager or public Runtime Web service.

Reuse the supported upstream snapshot/reference, locator, navigation, click/type/form, tabs, screenshots, and other applicable structured tool contracts. Do not claim that MCP exposes the full raw Playwright SDK or enable every upstream capability indiscriminately.

The Azents integration supplies:

- exact tool-execution Session/task authority and current resource binding;
- task-owned page/tab presentation and closure boundaries, including popups;
- the later-approved common Agent/human writer arbitration and stale-input checks;
- product lifecycle association without adopting upstream isolated-context disposal, global close commands, or CLI process lifetime as new product behavior;
- minimal task-opening/side-panel linkage, readable page glance, and existing image/file delivery integration.

No general browser permission settings, human-help request tools, backup/restore subsystem, or client-selected cross-Session scope is added by this proposal.

#### Source Grounding and Integration Limit

The Apache-2.0 Playwright MCP public `createConnection(config?, contextGetter?)` API accepts an externally owned `BrowserContext`. In the inspected implementation it wraps that context in `SimpleBrowser`, selects a context, and constructs `BrowserBackend`. `BrowserBackend.callTool` validates a schema and executes its handler.

This is credible evidence for external browser-resource supply, but it is not a task page allowlist, command/writer fence, or a documented before-tool hook. Passing an entire Session context to an unmodified MCP server is insufficient when multiple tasks share that context. A task-view/dispatch adaptation must be tested against the deployed package, not assumed from API names. The exact npm artifact and its Playwright dependency must be inspected together; upstream main is not proof of the package's precise implementation.

- [Public connection API](https://github.com/microsoft/playwright-mcp/blob/b8b4183e099f136cbec0388a6088d4aa2f6b9685/index.d.ts)
- [Inspected upstream connection implementation](https://github.com/microsoft/playwright/blob/647e485f2ba563ef055e2368fcc67bde67789cf0/packages/playwright-core/src/tools/mcp/index.ts)
- [Inspected upstream tool dispatch](https://github.com/microsoft/playwright/blob/647e485f2ba563ef055e2368fcc67bde67789cf0/packages/playwright-core/src/tools/backend/browserBackend.ts)

### Three Complementary Observation Surfaces

The added page-observation intent in `browser-261014/REQ-10` needs three distinct surfaces, not one raw DOM result:

1. **Concise reading glance:** read an appropriate region of the current rendered page locally and convert the selected DOM/HTML to readable Markdown with Turndown. Present source/scope and partial-content limits. This is deterministic extraction/conversion, not a separate LLM summarization service or an outside fetch of an authenticated page.
2. **Visual observation:** capture the rendered page and provide actual model image input through the existing image materialization path.
3. **Actionable DOM observation:** reuse the upstream structured accessibility snapshot and locator/reference mechanisms for precise interaction.

Turndown accepts DOM/HTML and has MIT licensing. It does not supply computed visibility, Shadow DOM/iframe completeness, virtualized offscreen content, or secret-field filtering; the page-reading adapter must define its bounded extraction surface and validate representative applications. An article/main-content extractor is not a universal web-application glance: Readability/Defuddle can remove short status, menu, or form information. They are not added as automatic fallback services or separate initial reader modes in this proposal.

Glance Markdown is not an input-target authority and does not replace the current actionable snapshot. A screenshot path alone is not model image input.

### Intentional Capture and Existing File Delivery

For `browser-261014/REQ-11`, preserve an intentional capture as an original Runtime image file under the current Session's authorized working context. Use existing `read_image`/ModelFile preparation for Agent image input and `present_file`/Exchange transfer for user preview/download.

Model image normalization currently may produce JPEG; it must not overwrite the preserved original capture delivered to the user. Intentional captured-file observation/export is distinct from continuously recording live viewer frames or input bytes into conversation.

The existing `read_image.py`, `present_file.py`, and [File Exchange Storage](../spec/flow/file-exchange-storage.md) provide concrete integration surfaces. No new browser-specific attachment store or file transport is proposed.

### Built-in Browser Usage Guidance — Proposed Addition

Provide one general browser usage Skill with the selected tool's focused API references through existing Skill facilities. Reuse Apache-2.0 OpenAI public Playwright Skill patterns where applicable, with attribution, but adapt Session/resource ownership and state lifetime instead of copying Coding-QA launches, sandbox disabling, or end-turn global tab cleanup.

Teach selecting glance/image/actionable DOM views, current-task handles, fresh snapshot discipline, result verification, ordinary-conversation authentication help, untrusted page-content handling, and non-replay of uncertain submissions. The Skill is usage guidance only; Runner/service admission and writer checks enforce authority.

This is a proposed delivery artifact, not a second runtime policy or a new Skill distribution system. Requester confirmation of the revised scope and Requirements must precede accepting this addition.

### Other Viable Directions and Trade-offs

- **Playwright CLI plus a Skill:** the official OpenAI public Playwright Skill uses this known tool. Its default browser creation, named sessions, global session listing/termination, and direct shell operation still need adaptation to D2 and task/writer authority. It is not already integrated simply because the CLI is published or installed.
- **Script-based Playwright API:** offers broader SDK use and persistent handles, as in OpenAI's public interactive Skill. Direct `Browser`/`BrowserContext` objects and arbitrary server-side code may reach other task pages or retain work beyond one call. Task restriction and writer mediation must be proven; full JavaScript execution is not assumed to be safely scoped by the outer tool call.
- **Chrome DevTools MCP:** a known attached-browser automation/inspection surface with Apache-2.0 licensing. Its page routing and server-local tool mutex do not establish Azents task ownership or shared Agent/human arbitration. It is a comparison alternative, not an extra initial backend.
- **A fixed three-tool surface backed by the Playwright SDK:** permits exact local contracts while reusing Playwright execution and auto-wait. Tool count is not a coverage limit; the product must maintain the supported action, target, event, result, and error contracts. The minimum earlier proposal did not establish those contracts for popups, frames, uploads/downloads, dialogs, event waits, and richer pointer/key input.

Codex reference evidence supports using known tools with guidance but does not prove that its private Chrome browser-client is reusable as an open-source dependency. Its public CLI and interactive Skills are separate workflows.

### Required Feasibility Gate Before Final Design

Demonstrate the exact package's external-browser attachment, same-Session login reuse, cross-Session isolation, multiple tasks in one Session, task-only tab listing/closing, popup attribution, Agent/human writer mediation, stale-ref handling, and executor disconnect without unrelated browser/profile destruction. Also validate representative glance output, actual model image input, original screenshot export, and absence of unintended sensitive content in ordinary logs/errors.

If task-view or dispatch adaptation requires replacing upstream snapshot/locator/action implementations or cannot enforce the approved scope, return that finding and revised alternatives. Do not silently create a large fork, allow an unrestricted debugging connection, or revert to the custom three-tool surface.

The requester selected Playwright MCP with WebMCP disabled. The exact accepted scope is recorded in D3 below. Updated page-observation/capture criteria and the proposed usage Skill remain separate from this tool-selection decision; their confirmation is not inferred from selecting MCP. Task writer ownership remains unresolved. No library integration, Skill creation, or product implementation has begun.

## D3. Use Playwright MCP and Disable Page-Provided WebMCP Tools

- Decision reference: `browser-261014/ADR-D3`
- Accepted by the requester on: 2026-10-14
- Affected confirmed requirements: `browser-261014/REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-8`, `REQ-9`.
- Approval scope: the supported Agent automation entry point and exclusion of page-provided tools. This decision does not approve the complete implementation Design.

### Decision

Use Microsoft Playwright MCP as the supported Agent browser automation contract and execution integration. Operate it within the Runner-owned browser-resource boundary established by D2 and the separately admitted Browser domain established by D1. The integration must bind calls to the currently authorized Session/task and its pages rather than provide unrestricted access to an entire shared browser.

Disable the experimental WebMCP feature that collects and exposes tools registered by a page. The inspected upstream configuration supports `webmcp: false` and the CLI equivalent `--no-webmcp`; verify the exact packaged behavior before implementation. Page-provided tools are excluded from this snapshot's supported tool surface. No user-facing re-enable setting is authorized by this decision.

The upstream tool list is an integration input, not authority to expose or execute every tool. Existing Session/task access and resource ownership must govern tool discovery and dispatch. Selecting MCP does not authorize unrestricted script execution, browser-wide resource operations, a public raw debugging endpoint, or automatic acceptance of page-defined tools. The exact initial upstream tool/capability set and any remaining material execution-scope choices must be settled before the final Design.

### Rationale

The requester selected MCP after comparing its reusable automation contracts with a fixed three-tool surface backed by the Playwright SDK. MCP reduces the amount of action/observation contract that Azents must maintain; Azents still owns resource association, authorization, task boundaries, and shared human/Agent input admission. Disabling WebMCP addresses the specific concern that visited pages could introduce additional tools.

The inspected [upstream README](https://github.com/microsoft/playwright-mcp/blob/b8b4183e099f136cbec0388a6088d4aa2f6b9685/README.md) documents WebMCP collection as enabled by default and provides the explicit opt-out. This is source evidence, not an executed package compatibility result.

### Alternatives Not Selected

- A fixed `open/observe/act` surface backed by Playwright SDK: viable with explicit expanded action/target/event contracts, but leaves their product maintenance to Azents.
- Playwright CLI or direct script/SDK execution as the primary Agent surface: different lifecycle and execution-scope integration obligations, not selected.
- Exposing page-provided WebMCP tools: excluded by the requester's explicit instruction.

### Consequences and Validation Obligations

- Validate the exact MCP package and Playwright dependency against external resource supply, Session-state reuse, task-only tab/frame/popup targeting, close/disconnect behavior, and current-generation rejection.
- Verify that a synthetic page registering a WebMCP tool cannot add it to the Agent-visible catalog or invoke it through the supported dispatch path when WebMCP is disabled.
- Compare the reviewed upstream tool schemas and configured capabilities with the product-supported set. Unexpected tools must not acquire authority through discovery alone.
- Integrate all supported mutating MCP calls with the same later-approved task writer arbiter used by human input; MCP-local call serialization alone is insufficient.
- Treat the rendered-text glance, actual image input, intentional capture export, and built-in usage guidance as separate delivery concerns. D3 selects the automation foundation, not their extraction libraries or all acceptance-criteria refinements.
- Return any package limitation requiring a material ownership, authority, or lifecycle change to the requester. Tool selection does not establish feasibility or permit a large replacement fork.

## D4 Candidate Brief: Source of Truth for Task Writer Admission

Question: should the authoritative current writer and input serialization live with the Runner's task registry, or be coordinated through durable Control-plane ownership records?

### Candidate A: Runner-Local Authoritative Writer State

The Runner arbitrates Agent and human input at the same current task boundary as the browser resources. Control establishes existing Session access and forwards admitted requests; UI/Control writer state is a projection, not an independent grant. Current-generation checks reject stale requests after replacement.

Benefits: one live enforcement boundary beside the pages; no new durable writer-state synchronization with the physical browser. Cost: writer continuity is not restored merely from saved profile bytes; fresh current state must be established after replacement.

### Candidate B: Durable Control-Plane Writer Coordination

Control stores the authoritative task writer grant; the Runner validates the current grant when admitting input and reports execution outcomes. This can preserve the recorded grant across Control/Runner reconnects but still cannot restore old live page identity or replay uncertain input.

Benefits: centralized writer-grant history and reconciliation. Costs: durable browser-writer state, exact grant-to-live-resource fencing, revocation synchronization, and failure handling when the two boundaries disagree.

### Recommendation and Remaining Scope

Recommend Candidate A for this snapshot: the current browser task and the final input-admission arbiter should share a live owner. Existing access remains Control's responsibility. This recommendation is not accepted.

Either option must preserve task-local contention, independent work, ordinary-conversation handback, fresh observation, and rejection of uncertain replay. Acquisition/release behavior for human attachments and in-flight commands is not selected by this source-of-truth question and must be resolved without inventing a dedicated help workflow.

## D4. Make the Runner Authoritative for Current Task Writer Admission

- Decision reference: `browser-261014/ADR-D4`
- Accepted by the requester on: 2026-10-14
- Affected requirements: `browser-261014/REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`.
- Approval scope: Candidate A's source-of-truth boundary. Exact writer acquisition/release and in-flight-command transition rules are not approved by this decision.

### Decision

The Runner owns the authoritative current writer state and final input admission for each live browser task. Supported Agent actions and human input pass through the same task-local arbiter alongside D2's resource registry. Control validates existing Session access; Control/UI projections cannot independently grant input ownership.

Current Runtime/Runner and task resource identity remain required. Runner replacement invalidates old writer grants and live page references rather than restoring them from native profile bytes. Establishing fresh writer/resource state does not itself signal successful human help, resume canceled work, or replay uncertain actions.

This decision introduces no durable Control-plane browser-writer grant registry. Native Session state continues under D2 and existing Runtime storage authority. The task-local boundary must not block unrelated Sessions or independent tasks.

### Rationale and Alternative

Final input admission and the physical browser task share the same live owner, avoiding grant-to-page reconciliation across a new durable ownership system. Durable Control-plane writer coordination was not selected; preserving a grant record would not preserve the old live page or make uncertain action replay safe.

### Validation Obligations

- Verify Agent/human and human/human contention at the final Runner admission boundary, including stale grants after replacement.
- Verify that Control/UI state cannot bypass final admission and existing read-only access cannot acquire a writer grant.
- Preserve independent task execution, ordinary-conversation handback, and fresh observation before Agent continuation.
- Resolve acquisition/release, attachment loss, and in-flight-command transitions before implementation Design approval.

## D3 Approval Withdrawal and Pending Replacement

On 2026-10-14, before implementation, the requester withdrew the MCP choice because adding local MCP execution and protocol relay/integration would complicate the Runtime command architecture. D3 remains above as the historical selection record, but its approval is withdrawn and it is not authority for implementation or final Design.

D1, D2, and D4 retain their accepted scope. The requester is discussing the original three-tool surface and additional essential capabilities implemented through Runtime commands. The replacement tool contract, action set, and any script-execution policy are not yet accepted. No MCP installation, product integration, or replacement implementation has occurred.

The requester subsequently approved the Runtime-command/Playwright-SDK replacement at 19:38 KST on the same date. That new accepted automation decision is recorded in [browsercmd-261014/ADR-D1](browsercmd-261014-session-browser.md#d1-use-three-typed-browser-tools-over-runtime-commands-and-playwright-sdk), with the consolidated product authority in [browsercmd-261014/REQ](../requirements/browsercmd-261014-session-browser.md). The original D3 record is preserved; it is not rewritten as the replacement decision.
