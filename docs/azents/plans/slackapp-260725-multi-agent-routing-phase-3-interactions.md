---
title: "Multi-Agent Slack App Routing Phase 3 Execution Plan"
created: 2026-07-25
updated: 2026-07-25
tags: [slack, external-channel, implementation, interactions, selection]
---

# Multi-Agent Slack App Routing Phase 3 Execution Plan

## Phase Boundary

- Phase: `PR 5/10 — Phase 3: Slack interaction and Agent selection`
- Branch/base: `feature/slack-multi-agent-app-interactions` → `feature/slack-multi-agent-app-routing`
- PR boundary: Admit Slack interactive callbacks durably, let participants select one eligible Agent for one retained conversation, continue through existing Agent-specific access approval, and present the selected Agent consistently on Slack output.
- Primary source decisions: `slackapp-260725/ADR-D1`, `ADR-D2`, `ADR-D6`, `ADR-D8`, and the runtime rollout boundary in `ADR-D7`.
- Primary requirement coverage: `REQ-5`, `REQ-6`, `REQ-8`, `REQ-9`, `REQ-10`, `REQ-13`, and `REQ-14`, plus transport continuity required by `REQ-3` and `REQ-12`.
- Deliverables: signed HTTP interaction admission; fenced Socket interactive-envelope admission; duplicate-safe interaction processing; message-shortcut and mention selector flows; bounded searchable/paged Agent catalog projection; stale-safe selection; retained source and approval continuity; current Agent name and optional image presentation across every Agent-associated Slack delivery.
- Non-goals: Workspace Multi App creation or management APIs; Workspace permission grants; public OpenAPI or generated-client changes; channel-default management mutations or authenticated Web handoff; Agent/Workspace management UI; deployment or infrastructure changes; living-spec promotion; database upgrade/stamp execution; Kubernetes or home-database writes; and the isolated Slack `files.completeUploadExternal invalid_arguments` investigation.

All current product writers remain Single-only. Multi App and multi-route rows may exist only in isolated transactional backend tests until PR 6 introduces the mode-aware management boundary.

## Mandatory Source Read and Traceability Gate

Before editing implementation files, the implementation owner must read these files in full:

- `docs/azents/requirements/slackapp-260725-multi-agent-routing.md`
- `docs/azents/adr/slackapp-260725-multi-agent-routing.md`
- `docs/azents/design/slackapp-260725-multi-agent-routing.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-implementation-plan.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-phase-1-schema.md`
- `docs/azents/plans/slackapp-260725-multi-agent-routing-phase-2-runtime.md`
- this Phase Execution Plan
- `docs/azents/spec/domain/external-channel.md`
- `docs/azents/spec/flow/external-channel-provider-ingress.md`
- `docs/azents/spec/flow/external-channel-authorization.md`
- `docs/azents/spec/flow/external-channel-lifecycle.md`
- `docs/azents/spec/flow/external-channel-delivery.md`

The implementation owner maintains a working checklist mapping `P3-D1` through `P3-D8` to implementation paths, tests, and final evidence. The primary agent verifies the complete phase diff and acceptance evidence before assigning the stable independent reviewer.

## Ownership and Paths

| Workstream | Owner | Expected paths | Output |
| --- | --- | --- | --- |
| HTTP and Socket interaction admission | `slack-app-impl-v3` | Slack public callback route, HTTP signature/admission services, Socket envelope dispatch, External Channel interaction repository/service code, focused provider tests | Verified raw-body or fenced-lease authentication, durable admission before acknowledgement, bounded projections, retry-safe processing |
| Selector and catalog projection | `slack-app-impl-v3` | External Channel interaction/selection services and Slack provider rendering/API helpers | Shared shortcut/mention selector, stable opaque IDs, bounded search/pagination, access-state projection, stale-safe submission |
| Conversation continuation and approval | `slack-app-impl-v3` | conversation admission, event/access/binding services and focused tests | Retained source materialization after selection, no pre-Allow execution, one binding/Session/release under duplicates and races |
| Agent presentation | `slack-app-impl-v3` | shared Slack delivery renderer, progress/control/error/file delivery call sites, capability parsing/validation | Bold current Agent name first, fallback text parity, capability-gated icon override with safe fallback |
| Provider contract and regression evidence | `slack-app-impl-v3` | adjacent HTTP/Socket/interaction/delivery tests; deterministic in-process fakes where available | Duplicate, expiry, stale view, catalog change, race, and transport evidence without introducing PR 8 testenv scope |
| Independent review | `slack-app-review-v2` | read-only review of the final diff and approved documents | Critical/Warning findings with exact evidence, or explicit no-findings result |

The implementation owner does not create child agents, commit, push, edit PRs, modify Kubernetes, run shared or configured database upgrades/stamps, or start PR 6 work.

## Cross-Cutting Authority and Safety Contract

- PostgreSQL interaction and conversation records are canonical. Slack callbacks, trigger IDs, response URLs, Socket envelopes, and broker messages only authenticate, route, or wake durable work.
- Slack sender, shortcut requester, action actor, modal submitter, uploader, approver, Agent administrator, Workspace administrator, connection creator, or wake-up never becomes an execution User.
- HTTP raw-body HMAC and replay-window verification occurs before trusted parsing or persistence. Socket processing requires the active fenced connection lease.
- A provider acknowledgement occurs only after the durable interaction admission transaction commits. It does not wait for catalog loading, Slack Web API calls, file enrichment, authorization, Session creation, or Agent execution.
- Raw interaction bodies, `response_url`, trigger IDs beyond their immediate bounded use, provider tokens, capability-bearing URLs, message/file bodies, and private image URLs are not logged or persisted.
- Selection always reloads the connection, resource, conversation admission, route, Agent lifecycle, catalog state, and access policy. Provider-returned Agent or route identifiers are untrusted.
- Mutations that create a binding or durable execution state retain the Phase 2 connection → route → resource → active binding → admission/request lock order and `owner_generation` fencing.
- Existing active bindings are immutable winners. No selector, changed default, duplicate submission, or approval callback may move an established conversation to another route.

## Acceptance Matrix

### P3-D1 — Durable HTTP and Socket interaction admission

Implementation:

- Extend the fixed Slack HTTP callback to distinguish verified JSON Events API payloads from form-encoded `payload` interactions without introducing another public endpoint.
- Select an HTTP connection candidate only from bounded untrusted App/Team identity, then verify the exact raw request body, timestamp, and signature before parsing the trusted interaction.
- Extend Socket Mode dispatch to interactive envelope types while requiring the current fenced connection lease and exact envelope acknowledgement semantics.
- Insert or load one `ExternalChannelInteraction` by `(connection_id, provider_interaction_key)` before acknowledging either transport.
- Persist only bounded routing projection: interaction type, callback/action identifiers, actor principal reference, source correlation, opaque admission identity, and safe categorical state.
- A duplicate transport callback returns or resumes the existing compatible interaction. A conflicting reuse of the provider key is rejected without mutation.
- Expired interactions transition durably to `expired`; malformed, cross-App, unsupported, or unauthorized payloads transition to or return a safe rejection without execution.

Required tests:

- Valid signed HTTP shortcut, block action, options request, and view submission admit once and acknowledge only after commit.
- Invalid signature, replay timestamp, malformed form payload, wrong App/Team, unsupported callback, and oversized fields create no trusted work.
- Socket interactive envelopes require the active lease, commit before acknowledgement, and deduplicate exact envelope retries.
- Duplicate HTTP bodies and Socket envelope IDs converge on one durable interaction; conflicting identities fail closed.
- Failure logs and persisted projections contain no raw body, token, response URL, trigger ID, message body, file bytes, or private URL.

### P3-D2 — Bounded Slack Web API interaction operations

Implementation:

- Add narrowly scoped provider operations needed for modal open/update and any option-loading or pagination response supported by the chosen selector design.
- Bound callback IDs, action IDs, block IDs, provider message/channel identifiers, query text, cursor/page size, modal private metadata, titles, labels, and option values.
- Modal private metadata contains only opaque server-issued interaction/admission identity plus integrity/version data; it does not embed connection, route, Agent, principal, message text, files, credentials, or authority.
- Do not hold a database transaction across Slack network calls.
- Model trigger expiry, Slack `ok: false`, view-hash conflict, retryable transport failure, and already-completed interaction as explicit safe outcomes.
- Provider mutation attempts remain retry-aware but never replay an already recorded one-attempt delivery as a new logical selection or execution.

Required tests:

- Modal open/update requests use bounded provider-safe payloads and no secrets.
- Expired trigger IDs, provider rejection, view-hash conflict, network failure, and duplicate processing produce deterministic durable outcomes.
- Large catalog navigation never creates an oversized modal or silently truncates eligible routes.

### P3-D3 — Shared selector and current catalog projection

Implementation:

- Use one selector flow for message shortcuts and mention-generated controls.
- List only `available` routes whose connection is the authenticated Multi App, whose Agent is active and in the same Workspace, and whose current access policy permits immediate use or a new access request.
- Project each selectable Agent as immediately available or `Access required`; hard-blocked or concurrently invalid candidates are unavailable and cannot be submitted.
- Sort deterministically by current Agent name with stable route identity as a tie-breaker.
- Support bounded paging or provider-supported option loading and bounded search. Every page/search requeries current catalog state.
- Never silently truncate the catalog. If provider limits prevent complete projection, expose paging/search rather than an incomplete terminal list.
- Selection values are opaque or stable IDs used only to reload trusted server state; they carry no authorization.

Required tests:

- Immediate, access-required, blocked, removed, inactive, and cross-Workspace routes project correctly.
- Search and page boundaries are deterministic and expose every eligible Agent without duplicates or silent omission.
- Catalog changes between open, option load, and submission are revalidated and fail safely.
- Forged connection, route, Agent, admission, and principal combinations never invoke an Agent.

### P3-D4 — Message shortcut source retention and selection

Implementation:

- Admit the `Ask an Azents Agent` message shortcut for one visible Slack source message.
- Persist or reuse the canonical resource, source message, immutable revision, principal, attachment metadata, and conversation admission before route selection.
- Preserve source text and file metadata route-neutrally. Do not download file bytes or materialize route-scoped pending context before selection.
- Open the selector within the provider interaction deadline from committed durable identities; expensive enrichment may continue after acknowledgement.
- On submission, lock and revalidate the connection, selected route, resource, active binding, and admission; apply `pending_selection -> selected` at most once.
- If the source resource is already bound, report the recorded Agent and instruct the participant to start a separate top-level conversation instead of changing the route.
- Duplicate shortcut callbacks or modal submissions reuse the existing interaction/admission and cannot create another binding, Session, or invocation batch.

Required tests:

- Shortcut source text, revision, principal, references, and file metadata survive selection and later approval continuation.
- No route pending context, Session, binding, batch, InputBuffer, or wake-up exists before valid selection and authorization.
- Duplicate and reordered callbacks preserve canonical identities and one selected route.
- Existing binding and alternate-Agent requests remain non-mutating.

### P3-D5 — Mention selector and default continuity

Implementation:

- A Multi App mention with an eligible channel default continues through the Phase 2 selected admission path without showing a selector.
- A Multi App mention without a valid default keeps one `pending_selection` admission and posts one idempotent thread control whose action opens the shared selector.
- The mention event itself does not have or synthesize a modal trigger. Only the participant block action supplies the trigger used to open the selector.
- Selecting an Agent affects only the current conversation admission. It never creates, changes, or implies a channel default.
- Duplicate mention events, control deliveries, actions, modal submissions, and concurrent default changes converge on the recorded binding or selected admission without rerouting.
- Single Apps never show the multi-Agent selector.

Required tests:

- Multi default mention selects its exact route and bypasses selector presentation.
- Multi mention without a default posts one control and creates no execution state.
- Duplicate event/action callbacks preserve one control, one admission, and at most one binding/Session.
- A concurrently added/changed default does not overwrite an already selected admission or active binding.
- Single App invocation behavior and existing HTTP/Socket event tests remain compatible.

### P3-D6 — Approval continuity and race convergence

Implementation:

- After valid selection, materialize the retained current source revision into only the selected route's pending context and apply existing grant/block/access policy.
- When access is required, create or reuse the Agent-specific access request and leave the conversation admission `awaiting_access`; create no Session, binding, run, invocation batch, InputBuffer, or wake-up.
- Allow revalidates the exact selected route and resource-wide active binding under the Phase 2 lock order, then creates or reuses one binding/Session and releases the retained source exactly once.
- Reject, expiry, route removal, connection termination, Agent decommission, stale catalog state, or hard block terminalizes the compatible admission/request without fallback to another route.
- Concurrent shortcut selection, mention selection, default routing, modal submission, and approval callbacks converge on one active resource binding and one root Session. Losing paths return recorded compatible state or a typed conflict.

Required tests:

- Access-required source text and file metadata are retained before Allow and released once afterward.
- Repeated Allow/Reject and duplicate selection callbacks remain idempotent.
- Selection/default/approval races produce one binding, Session, invocation batch, and initial release.
- A binding created for another route prevents rerouting and leaves no orphan Session.
- Every durable execution mutation reachable from this phase preserves `owner_generation` fencing.

### P3-D7 — Agent name and optional icon presentation

Implementation:

- Route every Agent-associated Slack output through one shared presentation boundary that resolves the current canonical Agent name from the binding route.
- Escape and bound the name, render it in bold as the first visible content, and begin top-level fallback text with the same name.
- Prepend one minimal Agent-name section before existing answer, progress, native `task_card`, native `plan`, control, approval, error, and file-related blocks without replacing provider-native content.
- File completion comments begin with the same bold Agent-name line.
- Extend or consume the sanitized Slack capability snapshot for message customization. Missing legacy capability is false.
- Use an icon override only for a validated provider-retrievable HTTPS Agent image and an enabled capability. Never change bot username or identity.
- Missing capability/image, private or invalid URL, and provider rejection fall back to the App bot icon without failing or duplicating the underlying delivery.
- No binding-time presentation snapshot is introduced; current Agent name/image is resolved for each delivery attempt.

Required tests:

- Text, block, progress, plan/task, selector/control, approval, error, and file-bearing outputs begin with the bold current Agent name and matching fallback text.
- Slack escaping, empty/long names, and block/text limits remain valid.
- Capability on/off and valid/missing/private/invalid image cases choose the correct icon behavior.
- Provider icon rejection preserves one delivery attempt and the durable delivery outcome without replaying content.
- Existing Single Apps gain the Agent-name line without requiring reauthorization and use the default bot icon when capability is absent.

### P3-D8 — Scope, observability, and rollout audit

Implementation:

- Preserve the PR 4 mode-aware routing and lifecycle invariants; do not reintroduce connection-only route ordering, route-qualified active-binding uniqueness, or Session↔binding lock inversion.
- Add safe structured outcomes only through established logging/metrics patterns for admission, deduplication, expiry, selector projection, stale submission, and icon availability. Do not add a new metrics subsystem.
- No public Multi management route, Workspace permission, OpenAPI schema/client, Web UI, testenv deployment fixture, Helm/Kubernetes change, living spec, or production Multi creation path enters this PR.
- Do not modify executed migrations. If a new durable constraint is proven necessary, report the exact deficiency to the primary agent before generating a new revision.

Required tests and audits:

- Existing Single HTTP and Socket event, access approval, binding, hydration, lifecycle, delivery, progress, error, and file-transfer tests remain green.
- Grep all interaction acknowledgement paths and prove durable commit precedes acknowledgement.
- Grep every selector submission and prove trusted route revalidation through the authenticated connection.
- Audit logs/projections/provider request capture for forbidden payloads and secrets.
- Audit all production/public/background/testenv `ExternalChannelAppMode.MULTI` writers; any new product writer is a blocker.
- Verify no generated clients, living specs, TypeScript UI, infrastructure, Kubernetes, or home files changed.

## Detailed Flows

### Signed HTTP interaction

1. Read the bounded raw request body once.
2. Extract only enough untrusted App/Team identity to locate a candidate connection.
3. Verify timestamp and HMAC against that candidate before trusted payload parsing.
4. Parse a bounded interaction projection and derive the provider idempotency key.
5. Insert or load the durable interaction and commit.
6. Acknowledge Slack immediately.
7. Continue modal/control/selection processing outside the acknowledgement transaction.

### Socket interactive envelope

1. Require the active fenced Socket lease and parse a bounded envelope.
2. Insert or load the durable interaction by envelope ID and commit.
3. Send the exact envelope acknowledgement.
4. Continue the same transport-neutral interaction processor used by HTTP.
5. Lease loss, duplicate envelope, reconnect, and cancellation never acknowledge uncommitted new work.

### Shortcut or mention selection

1. Persist or load route-neutral canonical source and one conversation admission.
2. If already bound, return the recorded Agent without mutation.
3. If a valid default already selected the admission, continue normal authorization.
4. Otherwise open or update the shared selector from an admitted interaction.
5. On submission, lock connection → selected route → resource → active binding → admission/request.
6. Reload current catalog/access state and apply one immutable selection.
7. Project retained source to selected-route context and continue through grant or access request.
8. Create execution state only after authorization; provider callbacks never supply execution User authority.

## Test Placement

Prefer focused tests adjacent to the changed boundary:

- HTTP route and raw-body signature/form parsing under the current public Slack callback tests;
- Socket envelope dispatch and acknowledgement under the current Slack Socket service tests;
- interaction repository/state transitions under `repos/external_channel/`;
- shortcut, selector, mention, admission, approval, and race behavior under `services/external_channel/`;
- Agent presentation under the shared Slack delivery/progress renderer tests and directly affected delivery services.

Use real PostgreSQL/Testcontainers tests for uniqueness, row locks, and concurrency where the repository suite already provides that boundary. Mock-only call-order assertions supplement but do not replace database race evidence.

## Final Validation Gate

All commands run after the final implementation edit.

From `python/apps/azents`:

1. `uv run ruff format .`
2. `uv run ruff check .`
3. `uv run pyright`
4. focused HTTP, Socket, interaction, selector, event, access, binding, delivery, progress, file, and PostgreSQL concurrency tests
5. `uv run pytest`

From the repository root:

6. `git diff --check`
7. inspect `git diff --name-only` against this phase boundary
8. audit commit-before-acknowledgement for every interaction transport
9. audit selection revalidation, lock ordering, and `owner_generation` fencing
10. audit forbidden secret/raw-payload persistence and logging
11. audit every production/public/background/testenv Multi creation match
12. verify no public OpenAPI/generated client, living spec, TypeScript UI, infrastructure, Kubernetes, or home file changed

Docker/Testcontainers absence may produce a declared local skip, but it is not positive PostgreSQL concurrency evidence. PR 5 is not CI-green until its PostgreSQL and provider-contract tests execute in CI and pass.

## Required Completion Report

The implementation owner returns one complete report containing:

- explicit confirmation that all mandatory source documents were read in full;
- every `P3-D1` through `P3-D8` acceptance item mapped to changed paths and tests;
- exact commands, pass/skip/fail counts, and Docker/provider-fixture limitations;
- all production interaction acknowledgement, selector submission, binding creation, and Agent-associated Slack delivery call sites audited;
- confirmation that no execution User was inferred from provider actors and every touched durable execution mutation retained `owner_generation` fencing;
- confirmation that no Multi App product creation path, public API/client, Web UI, infrastructure, living spec, or executed-migration edit entered the diff;
- changed files and any residual risks or blockers; and
- no commit, push, PR edit, or PR 6 implementation.

The primary agent then runs the final quality and scope checks, assigns the stable independent reviewer, applies any accepted localized fixes directly, and only after a clean review commits and opens PR 5 against PR 4.
