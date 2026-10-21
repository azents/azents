---
title: "Direct Google Workspace Tools Migration Decisions"
created: 2026-10-21
updated: 2026-10-21
document_role: primary
document_type: adr
snapshot_id: google-261021
tags: [google, toolkit, oauth, migration, security, architecture]
---

# Direct Google Workspace Tools Migration Decisions

- Snapshot: `google-261021`
- Document reference: `google-261021/ADR`
- Mode: Collaborative.
- Decision owner: requester.
- Authority: [confirmed Requirements](../requirements/google-261021-direct-workspace-tools.md).
- ADR-D1 records the requester-confirmed OAuth authority model. ADR-D2 records
  server-issued minimal Picker credentials. ADR-D3 records omission of the
  Google-specific content scanner. ADR-D4 records the drained one-time cutover.
  All four material topics have a selected direction.

## System Framing

### Current authority and lifecycle

The current [Google Connection Spec](../spec/domain/google-connection.md) and code at
`81a3503318fac347f687f416f7ac231315e5c5cd` establish:

- `RDBToolkitConfig.config` owns task selection, timeout, and connection-risk
  acknowledgement; the Toolkit owns identity, namespace, enabled state, and
  Workspace/Agent/User scope.
- `RDBGoogleConnection` owns exactly one current encrypted subject/client-bound
  grant per Toolkit. It is separate from the operator application and from
  unpublished OAuth attempts. Ordinary access-token renewal retains grant identity;
  confirmed reconnect replaces it.
- `GoogleRuntimeService` and `GoogleRuntimeRepository` load current Session owner,
  delegation, personal access, task selection, actual grants, and client evidence.
  Detached SDK renewal is fenced on finalization, and tool admission repeats after
  renewal. Schema caches are not authorization.
- `GoogleServiceMcpToolkit` currently owns dynamic remote schema discovery, service-
  prefixed tool names, per-Toolkit/service snapshots, full argument/result content
  inspection, and Artifact extraction. Generic MCP machinery is shared with other
  providers and remains authoritative for those providers.
- `GoogleSetup`, its container, callback management, and the OAuth services use
  staged connect/reconnect, exact-context resume, actual partial-grant review,
  local cancellation, and uncertain-publication outcome inspection.
- Strict task-typed payloads appear not only in current config but also encrypted
  setup/reconnect targets and completed outcome JSON. A schema replacement must
  cover all these persisted boundaries, not just the visible settings form.

### Requirement gaps

| Requirements | Current gap | Reusable authority |
| --- | --- | --- |
| REQ-1 | Execution and schemas depend on official MCP | Existing built-in `google` provider and verified OAuth account |
| REQ-2, REQ-7 | Eight tasks currently cap tools as well as request scopes; service state is derived from tasks | Toolkit identity/config, manager ownership, actual grants, current-state execution checks |
| REQ-3 | No send/filter-management tools; draft modification and label-management breadth are narrower | Gmail actual-grant evidence and current admitted operations |
| REQ-4 | No status-event management or secondary-calendar creation | Calendar read/availability/edit and current account binding |
| REQ-5, REQ-10 | Restricted-file work and whole-Drive read exist, but no whole-Drive write choice or Picker surface | Stored Google client/account and action/scope checks |
| REQ-6 | Replace old task ceilings with grant-derived actions while preserving actual scopes and service state; typed historical payloads still use old definitions | One current grant, exact reconnect target checks, historical outcome identity |
| REQ-8 | Remove Google-specific scanner and binary rejection while preserving data/file authority and resource limits | Canonical file/Session authority, credential confidentiality, parser and transfer limits |
| REQ-9 | Operator/setup descriptions refer to MCP/Preview; management has no independent service-toggle path | Existing setup/reconnect, management routes, generated clients, localized components |

### Fixed and derived outcomes

These are briefings, not reopened questions:

- Direct Gmail/Calendar/Drive tools replace the Google-specific official MCP lane.
  The generic MCP provider and Google Analytics are unaffected (REQ-1).
- Preserve connected account/client, Toolkit identity/delegation, service state, and
  actual Google scopes (REQ-6, REQ-8). Within enabled services, actual grants now
  admit all sufficiently authorized supported tools; old selected-task ceilings
  are removed rather than retained as a migration layer.
- Whole-Drive is the default file boundary for new configuration; app-authorized-
  file mode and selection in connection settings are supported. Neither the default
  nor migration requests broader scopes for old restricted-file connections
  (REQ-2, REQ-5, REQ-6, REQ-10).
- No per-operation approval machinery is introduced (REQ-2, REQ-9, Non-Goals).
- Service state, provider scope, resource capability, and canonical owner
  admission remain distinct. Service off must affect newly admitted calls and
  must not claim to undo already accepted remote effects (REQ-7, REQ-8).
- Supported external-service SDK public APIs are required by repository convention.
  Local API calls are not a license to reimplement provider protocols manually.
  The official Python client provides Gmail/Calendar/Drive resources. The use of
  local bundled API descriptions is distinct from exposing remote-discovered MCP
  schemas to the model.
- SDK automatic renewal and mutation retry must not bypass owner-fenced renewal or
  replay uncertain writes. The official client's `HttpRequest.execute` defaults to
  zero retries, and its `httplib2.Http` instances are not thread-safe. Request-local
  transport/lifecycle, bounded off-event-loop work, and explicit retry ownership
  require verification; they are not a new user-selectable mode.
- Existing file resources must retain canonical Session/Run and size/integrity/
  lifecycle boundaries described in [File Exchange Storage](../spec/flow/file-exchange-storage.md).
  A backend filesystem path is not a Runtime file authority.
- Google-specific prompt-content screening is omitted under revised REQ-8. Its
  removal does not remove account admission, typed data validation, file/path
  authorization, parser limits, or transfer-integrity checks.
- No new user-facing versioning feature or permanent legacy execution fallback is
  required. Existing revision/CAS and owner-generation checks are retained.

## Material Technical Decision Docket

Candidate identifiers C2-C4 below are not accepted ADR-D identifiers. Each accepted
choice will be appended as the next ADR-D entry with its authority and consequences.
The former C1 selected-action representation question was withdrawn after the
requester changed the product authority model; neither proposed representation
was selected.

- [x] **ADR-D1 — Accepted:** actual OAuth grants determine supported actions; service
  switches and existing owner/access checks remain. No selected-action ceiling.
- [x] **ADR-D2 — Accepted, feasibility conditional:** server-issued minimal
  `drive.file` Picker token with actual-scope validation and no broad-token
  fallback. Persistent grant transitions still follow actual returned evidence.
- [x] **ADR-D3 — Accepted:** omit Google-specific content scanning and its blanket
  binary rejection; retain normal execution/data/file safeguards.
- [x] **ADR-D4 — Accepted:** drained one-time cutover, preservation of published
  connections, restart of incomplete setup, and pre-cutover restore boundary.

Product scope is fixed by the confirmed Requirements. A newly discovered user-
visible contradiction returns to Requirements, rather than being silently decided
as an implementation detail.

### C2. Picker and file-scope credentials

**Question:** Should Picker receive an independently issued minimal token through a
manager-bound server flow, or use a browser-owned Google authorization flow that is
bound back to the exact saved account and app?

**Evidence and required boundaries**

- The Google Picker JavaScript API consumes an OAuth access token. It also needs a
  browser API key and Cloud project/app ID, which current Google operator settings
  do not expose as Picker preparation fields.
- Never hand the existing multi-service token to the browser merely to open Picker.
  The refresh token and unrelated Gmail/Calendar scopes remain server-only.
- Official Google documentation describes scoped refresh requests and
  `include_granted_scopes=false` for separate authorization, but an actual returned
  token must be checked. Local filtering of a declared scope list cannot narrow a
  credential. Do not assume generic Cloud Storage credential-access-boundary token
  exchange applies to Drive.
- A pure app-authorized-file mode cannot execute Drive operations with a broad
  `drive`/`drive.readonly` token and call the result Google-enforced limited access.
  Prior broad consent, over-grants, renewal, and combined grants must be handled at
  the credential boundary, not merely in a saved file-ID list (REQ-10).
- A separate browser authorization cannot replace the saved grant or change its
  subject silently. Manager authority and verified provider account binding are
  independent. A login hint is not proof of subject identity.

**Option A — Server-issued minimal Picker token (recommended, conditional)**

Selected as ADR-D2 on 2026-10-21; the evidence and unselected alternative below
remain the decision context.

The manager-authenticated backend uses the exact connected subject/client-bound
refresh credential through the existing supported OAuth SDK to request an
independent short-lived token restricted to `drive.file`. Verify actual returned
scope evidence, then recheck the manager, current connection/client and service
state before returning it to the authorized settings page. The browser uses it
only in the Picker flow; it receives no refresh token or main multi-service access
token. Return no token if the provider denies the request, omits sufficient scope
evidence, or returns unrelated/wider scopes.

- Benefit: the manager operates the already connected account without a second
  browser-selected Google account becoming another identity authority. No extra
  durable Picker credential store is required by this option.
- Cost/risk: the returned short-lived bearer token is a real Drive app-file
  credential, not a one-use Picker-only capability. Browser compromise can exercise
  its Google-granted file authority until expiry. Short lifetime and protected
  delivery do not make it immediately revocable through a local service switch.
- The issuance response is non-cacheable, is not persisted in browser storage,
  URLs, logs, tool results or model context, and must not overwrite the primary
  access-token/granted-scope evidence or perform ordinary-grant CAS with this
  narrower token. Unexpected refresh-token rotation must not be discarded or
  silently applied without a defined current-grant policy.
- Feasibility is conditional: Google documents the optional subset `scope` on a
  refresh request, and SDKs support public refresh operations, but a live Google
  receipt for this deployment has not been tested. Never claim narrowing merely
  because the request included `scope=drive.file`.

**Option B — Separate browser Google authorization for Picker**

Use Google's browser authorization flow to request the minimal Picker token, with
prior-grant inclusion disabled where supported. Bind a server-validated actual
identity/client/scope result to the exact manager-authorized saved connection.
Do not use an email hint, callback file IDs, or requested scopes alone as proof.

- Benefit: main server-held refresh credentials need not be used for Picker-token
  issuance.
- Cost: another authentication/identity/callback path, Google browser-account
  selection and potential prompts. A manager of a shared connection may not be
  signed into the connected Google account; mismatch must fail instead of replacing
  the account. This adds more lifecycle and failure handling than Option A.
- Both options still expose a real minimal token to the authorized browser because
  Google's Picker consumes one. Neither option authorizes broad-token fallback.

The choice covers Picker credential issuance, not a claim that every broad-to-
limited persistent grant transition is already solved. Retain actual scope evidence
and perform ordinary reconnect/validation for a requested file-boundary change;
if broad scopes remain, report them and do not label the grant restricted. No
local file-ID list may substitute for Google-enforced app-file access.

### C3. File transfer and content-inspection boundary

Resolved by the requester choosing omission of content screening, recorded in
revised REQ-8 followed by ADR-D3. The earlier proposal to preserve text scanning
while allowing opaque binary transfer was not selected.

**Evidence and constraints**

- Current `GoogleServiceMcpToolkit.screen_google_result` rejects nontext embedded
  resources and unknown binary. `inspect_google_content` inspects bounded complete
  JSON-compatible structures and known normalized/decoded text patterns, not file
  malware or all semantic prompt injection.
- `ArtifactService` provides canonical-authority publication and verified-object
  transfer. Existing import/presentation/runtime-transfer paths provide independent
  storage and integrity authority. Reuse these instead of arbitrary backend file
  paths or provider capability URLs.
- Extracting readable text is different from transferring original bytes. Treating
  a PDF/Office file's extracted text or metadata as proof that all its bytes were
  semantically inspected would be false. Oversized, encrypted, malformed, or
  unsupported content requires explicit failure/opaque-transfer treatment.
- A retained blanket binary rejection conflicts with meaningful binary attachment
  and format-transfer targets. Conversely, removing it without defining where
  untrusted bytes may flow would weaken existing protection silently.

**Reference findings**

The inspected community reference has prompt-injection risk guidance and
authentication/path/resource controls, but no equivalent prompt-pattern scanner
was found in its tool/core/auth paths or registered middleware. Its Drive tools
support image bytes and original file download.

Official Google Workspace MCP guides explicitly instruct users to screen prompts
and responses with Model Armor or a documented own solution. Model Armor has
API/project-policy configuration; this is not proof of unconditional default
inspection or equivalence with Azents's regex scanner. Neither a community
implementation nor this product decision establishes Google policy compliance for
direct API use.

### C4. Cutover and recovery boundary

Selected as ADR-D4 on 2026-10-21. The requester reported that the integration is
not yet in use and accepted the drained single cutover. This is not evidence that
all target databases are empty or authority to delete published connections.

**Evidence and candidate consequences**

- Published config, encrypted setup/reconnect targets, completed outcome JSON,
  service-specific MCP snapshots, tool-search working sets, and live captured
  handlers contain old task/name/schema assumptions.
- Current reconnect targets compare config, and renewal CAS compares the current
  config. Migration/local edits must defeat stale publications and renewal writes
  without corrupting historical outcomes.
- A drained cutover avoids simultaneous interpretation of old/new permission
  contracts but needs a defined maintenance/drain window and one explicit restore
  boundary. It must cover OAuth callbacks arriving during cutover.
- A rolling transition can reduce downtime but introduces temporary dual-read/
  write/cutover responsibilities, old-worker fences, and a later removal boundary.
  This is a migration option to be decided, not an already approved legacy fallback.
- Rollback cannot mean replaying a sent email or undoing Google consent/remote
  effects. Schema/settings restore and application rollback are different from
  reversing external effects.

**Option A — Drained one-time replacement (recommended)**

Accepted below as ADR-D4.

Stop admission of old Google setup/execution mutations and drain or safely fence
old owners before modifying their persisted contracts. Preserve published Toolkit
IDs, current subject/client-bound grants, ownership/delegation, service state,
timeout and unrelated metadata. Transform old task config into service state and
OAuth request intent; actual scopes determine actions under ADR-D1. Retire the
scanner acknowledgement authority under ADR-D3. Invalidate and scrub unpublished
old setup/reconnect attempts so their callbacks cannot publish; managers restart
those incomplete attempts through ordinary setup. Preserve completed outcome
identities without reactivating credentials. Retire only Google-specific MCP
snapshot state and stale deferred-schema references, then start the new lane.

- Benefit: one authoritative contract after migration, no temporary old/new action
  interpreter or permanent Google MCP execution fallback.
- Cost: a controlled service interruption during release; incomplete Google
  connection setup must be restarted. The exact drain scope and operational
  commands must be explicit in the Design, not represented as already supported
  per-Google maintenance features.
- Failure: validate stored shapes before mutation, avoid partially starting the
  new application against an incomplete transformation, and define a pre-cutover
  restore checkpoint. Returning to the old application may require restoring old
  persisted shapes; it is not necessarily an image-only rollback.

**Option B — Bounded rolling compatibility transition**

Temporarily read/write or transform both persisted contracts, coordinate old-worker
fences, and retire the old contract in a later deployment.

- Benefit: potentially smaller release interruption and more continuity for old
  setup attempts if specifically implemented and verified.
- Cost: additional interpretation, fencing and migration lifecycle across multiple
  releases, including a deliberate removal boundary. This is more than adding a
  fallback flag and is not authorized implicitly by the feature request.

Neither option reverses Google consent or completed external effects. No production
change, drain, migration command, runtime mode, or rollback procedure has been
authorized or executed.

## Removal and Replacement Inventory for the Future Design

| Existing surface | Replacement obligation | Retained authority |
| --- | --- | --- |
| Google endpoint constants and `GoogleServiceMcpToolkit` discovery/calls | Direct supported-SDK effects and local tool contracts | Current owner/client/grant checks and supported SDK rule |
| Old eight-task execution ceilings | ADR-D1 scope-derived capability projection; retain request intent only where needed for OAuth | Actual grants, existing service state, owner/access under REQ-6 |
| Google MCP snapshots/captured schemas/deferred working-set names | Local schemas and C4 retirement boundary | Historical tool results remain history, not current execution authority |
| Old typed pending setups/reconnect targets/outcome JSON | C4 transition and historical read contract | Exact publication identity and no credential resurrection |
| Google MCP-only fake routes and discovery tests | Direct API fixtures and policy/lifecycle/SDK tests | Existing OAuth/identity and owner/concurrency tests where still relevant |
| Google-specific scanner, argument/result/schema screening hooks, and blanket binary rejection | Remove under REQ-8 and ADR-D3; normal typed validation and file/resource checks remain | Current OAuth, owner, canonical file and size/integrity authority |
| Scanner-only tests, content-risk acknowledgement fields/checks, and scanner claims in setup/generated contracts | Remove or migrate dependent persisted payloads at the C4 boundary; retire obsolete tests | Existing setup review/disconnect and secret-redaction behavior remain |
| MCP/Preview setup copy and old task-only forms | Direct API preparation, service switches, OAuth request bundles, Picker | Current ownership, partial consent, callback and reconnect semantics |
| OpenAPI and generated clients | Regenerate after approved management contract changes | Existing client-generation workflow |
| General MCP transport, snapshot repository, Google Analytics | No broad removal | Other integrations still depend on them |

## Verification Framing

The complete Design must trace each requirement through an accepted decision or
retained authority and specify E2E-first verification. Required lanes include:

- A migrated existing connection with unchanged identity/delegation, actual scopes
  and service state; newly supported tools follow those scopes rather than old
  draft/create-only execution ceilings.
- New full-Drive default and selected-file mode without fabricating scopes.
- Worker direct API execution with actual grant subsets, service off, owner/client
  changes, reconnect/renewal races, and no uncertain-write replay.
- Picker authorization subject/client/scope validation, cancelled selection, and
  unrelated credential nondisclosure. A synthetic Picker contract is not live
  Google account verification.
- Actual Gmail/Drive attachment and import/export flow under ADR-D3, canonical
  file access, parser limits and size/integrity checks. Retire obsolete scanner-only
  tests rather than adding tests solely asserting a removed feature is absent.
- Exact pending-attempt, historical outcome, stale handler, and snapshot cutover
  behavior from C4.
- Component-owned settings matrices and browser E2E only where Google callback or
  independently deployed boundaries require a browser.

## Agent-Owned Local Details

Exact identifiers, module/helper layout, equivalent typed structures, parser
composition, fixture names, and local error-copy organization remain implementation
choices when they introduce no extra state, authority, modes, contracts, or user
behavior. Public SDK use, current proxy behavior, cleanup lifetimes, and bounded
resource usage still require concrete feasibility evidence.

## Primary References

- [Google Picker web integration](https://developers.google.com/workspace/drive/picker/guides/web-picker)
- [Google Identity JavaScript authorization reference](https://developers.google.com/identity/oauth2/web/reference/js-reference)
- [Google OpenID Connect API reference](https://developers.google.com/identity/openid-connect/reference)
- [Drive scope semantics](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Official Python client: getting started](https://googleapis.github.io/google-api-python-client/docs/start.html)
- [Official Python client: thread safety](https://googleapis.github.io/google-api-python-client/docs/thread_safety.html)
- [Official Python client: request execution and retries](https://googleapis.github.io/google-api-python-client/docs/epy/googleapiclient.http.HttpRequest-class.html)
- [Official Google Workspace MCP security](https://developers.google.com/workspace/guides/configure-mcp-security?hl=en)
- [Community security guidance](https://github.com/taylorwilsdon/google_workspace_mcp/blob/484f64b5a43ddfed0d1e214f7e1038076d904c5b/SECURITY.md)

## Accepted Decisions

### ADR-D1. Actual Google grants are the action authority

- Accepted: 2026-10-21, by the requester, following confirmation of the revised
  Requirements.
- Authority: `google-261021/REQ-2`, `REQ-3`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`,
  `REQ-9`, and `REQ-10`.

**Decision**

For supported operations, derive exposure and invocation eligibility from
sufficient actual Google scopes inside enabled services, then apply canonical
account/owner, Toolkit/Agent access, and resource-capability checks. Keep a bounded
local catalog mapping supported operations to sufficient scopes. That catalog is
implementation capability metadata, not a manager-selected permission store.

OAuth request bundles configure requested scopes only. Do not persist selected
effects or selected groups as a second action authorization ceiling, and do not
carry forward the old task allowlists as hidden migration restrictions. Service
switches remain independent. A scope does not authorize arbitrary provider methods
outside this feature's supported catalog or override resource/owner protections.

**Alternatives not selected**

- Separate selected effects intersected with grants.
- Selected groups intersected with an operation ceiling.

Both add the extra Azents action restriction the requester explicitly declined.

**Consequences**

- `gmail.compose` and `gmail.modify` may expose supported send operations without
  a separate send switch. `drive.file` may expose supported sharing/ownership work
  for eligible app files. Request descriptions must explain these real bundles.
- Existing enabled services may gain supported operations under unchanged broad
  grants. REQ-6 now preserves actual grants rather than exact old tool coverage;
  management must explain the changed capability projection.
- Migration still cannot invent whole-Drive write authority from `drive.file`, or
  from `drive.readonly` combined with `drive.file`. Unselected/off services and
  current ownership/delegation remain binding.
- Local changes to requested bundles do not revoke Google consent. Reflect actual
  returned evidence; do not relabel a broad grant narrow merely by editing config.
- Pure selected-file behavior still requires a credential for which Google
  enforces the restricted boundary. Minimal Picker credential issuance and any
  broad-to-limited grant transition remain C2, not resolved by this decision.
- This decision does not add operation approval or authorize implementation,
  production migration, external effects, or deployment.

### ADR-D2. Server-issued minimal credentials for Google Picker

- Accepted: 2026-10-21, by the requester selecting C2 Option A.
- Authority: `google-261021/REQ-8`, `REQ-9`, `REQ-10`, and ADR-D1.
- Feasibility: conditional pending deployment-specific live Google scope receipts;
  deterministic fixtures must also cover denials, over-grants, missing scope
  evidence, stale manager/grant context, and credential nondisclosure.

**Decision**

Issue Picker credentials at the manager-authenticated server boundary using the
exact current connected Google subject and client. Through a supported OAuth SDK,
request a separate short-lived access token for `drive.file` from that connection's
refresh credential. Admit browser delivery only after verifying that returned
scope evidence permits the requested file access and contains no wider or
unrelated scopes, and after repeating current manager/connection/client/service
admission. Do not infer granted scopes from the request.

Keep the main multi-service access token and refresh credential server-only.
Return the minimal access token only to the authorized management browser through
a non-cacheable response, keep it in transient memory for the Picker, and exclude
it from URLs, durable browser storage, logs, model inputs, and tool output.
Discard unneeded transient access-token material after use; browser memory cleanup
does not revoke copies already issued by Google.

Scope narrowing must be a provider-issued credential property, not a mutated local
scope list. Provider refusal, unknown scope evidence, or an over-granted receipt
must not fall back to a broad token. The issuance flow does not replace the saved
account, the primary access-token evidence, or the product's service/grant model.

**Alternatives and consequences**

- A separate browser-owned Google authorization/account-selection lane is not
  selected. It would create another account-matching and callback lifecycle.
- The browser receives a real short-lived `drive.file` bearer credential, not a
  Picker-only or one-use capability. Until Google expiry/revocation it can exercise
  its Google file authority; local service off does not revoke the already issued
  credential. This risk is part of the selected browser integration.
- Current operation/manager ownership checks must bracket issuance I/O. No provider
  call occurs inside a database transaction; delayed success cannot authorize a
  manager whose access or connected grant changed.
- Unexpected refresh-token rotation requires a concrete current-grant-fenced
  preservation/failure path before final Design approval. It must not be silently
  discarded, nor may a scoped issuance receipt overwrite the main grant's scope
  evidence. That mechanism is not declared complete by this decision.
- The Design must include optional Picker operator preparation (browser API key,
  app/project ID, API activation and relevant origin restrictions), clear missing-
  preparation recovery, and evidence for returned scope and account binding.
- Broad-to-limited saved authorization still uses ordinary reconnect and actual
  evidence. A broad credential is not relabeled selected-file-only, and a local
  file list is not a replacement for Google enforcement.
- A failed live feasibility check returns the exact SDK/provider limitation for
  redesign; this decision does not preauthorize an alternate credential path.
- No production authentication, token issuance, migration, or code implementation
  has been performed as part of accepting this decision.

### ADR-D3. Omit Google-specific prompt-content screening

- Accepted: 2026-10-21, by the requester after reviewing the local scanner and the
  community/official MCP comparison.
- Authority: revised `google-261021/REQ-8`, `REQ-9`, and Non-Goals.

**Decision**

The direct Google integration does not carry forward `inspect_google_content`,
Google-specific schema/argument/result prompt-pattern screening, or the blanket
rejection of binary results solely because the text scanner cannot inspect them.
Model Armor and substitute semantic content-scanning services are not introduced.

Retain supported tool contracts and typed input/result validation, OAuth actual
grant checks, service switches, canonical execution ownership, Toolkit/Agent
access, exact connected-account identity, credential redaction, file/resource/path
admission, transfer integrity, and bounded file/parser/network operations.
Transferred or model-readable Google content remains untrusted data; no inspected-
safe, malware-free or prompt-injection-prevention claim is made.

**Alternatives not selected**

- Preserving the text scanner while allowing opaque file transfer.
- Retaining blanket binary rejection.
- Adding Model Armor or another content-screening dependency.

**Removal and migration consequences**

- Replace the Google MCP wrapper with direct tool handlers without migrating its
  scanner calls. Remove the unused Google-only scanner module and scanner-only
  tests when their last supported call site is retired.
- Retire `security_risk_acknowledged` and scanner-specific connection publication/
  runtime gates, dependent DTO fields, localized claims, and generated contract
  surfaces. Their persisted occurrences in config, unpublished setup/targets and
  completed outcomes are covered by C4; do not discard credentials merely because
  the scanner acknowledgement field is retired.
- Keep ordinary connection/account review, local disconnect handling, and existing
  user/manager authorization. No replacement execution-approval workflow is added.
- Allow supported binary attachment/download/import/export operations through
  normal authorized file paths. A parser may reject malformed/unsupported content
  for extraction; transfer eligibility is not a semantic inspection verdict.
- Official MCP documentation's screening directions must not be represented as
  satisfied merely by removing MCP transport. Assess applicable direct-API user
  data/developer policy before claiming compliance or production readiness. This
  decision accepts a feature boundary, not an exemption from external policy.
- This is design authority only. Runtime scanner code, production connections,
  deployment and live Google data have not been changed by this decision.

### ADR-D4. Drained one-time cutover

- Accepted: 2026-10-21, by the requester selecting C4 Option A and reporting that
  the integration is not yet in use.
- Authority: `google-261021/REQ-1`, `REQ-6`, `REQ-7`, `REQ-8`, `REQ-9`, ADR-D1,
  and ADR-D3.

**Decision**

Use a stopped/drained application cutover for the changed Google contracts, not a
multi-release dual-contract compatibility lane. Stop admission of old management
mutations and prevent old workers from running captured Google handlers before
the data transformation. Quiescence can be achieved using existing deployment
controls; do not create a permanent product maintenance mode for this feature.

Preserve any published Google Toolkit identity, current account/client grant,
ownership/delegation, actual scopes, enabled service state and unrelated metadata.
The unused-integration context reduces continuity requirements but does not
authorize assuming empty tables or deleting published grants.

Invalidate and scrub unfinished old connect/reconnect attempts; their callback
must fail as no longer usable and the manager starts ordinary setup again. Keep
published outcome identity inspectable without credential resurrection. Transform
saved configs and historical outcome payloads, remove obsolete acknowledgement
authority and Google-specific schemas/snapshots, and start only the new contract.

**Alternatives and recovery**

- A bounded rolling compatibility deployment is not selected. No old/new execution
  switch, task-ceiling fallback or permanent legacy interpreter is introduced.
- Retain an authorized pre-cutover database checkpoint and compatible application/
  configuration artifacts. Pre-admission failure returns to that checkpoint if
  needed; old application code must not be started against unverified new shapes.
- Resuming old application code after new writes is not a blind image rollback.
  Stop admission again and assess/transform or restore under explicit operator
  authority; remote email/file/calendar effects and Google consent are not undone.
- Validate and report malformed/unexpected stored records before mutation. Do not
  silently skip affected connections or invent missing scope evidence.
- Verify empty-install, populated saved-connection and incomplete-attempt migration
  cases. Keep namespace/access rows and non-Google Toolkit state untouched.
- This accepts the release design. No drain, database backup/restore, migration,
  release, deployment, or live Google effect has been executed or approved for
  immediate execution by this conversation.
