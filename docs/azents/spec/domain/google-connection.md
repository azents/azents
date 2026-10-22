---
title: "Google Connection"
created: 2026-10-14
updated: 2026-10-22
tags: [google, toolkit, oauth, backend, frontend, engine, security]
spec_type: domain
domain: google-connection
code_paths:
  - python/apps/azents/src/azents/core/google_*.py
  - python/apps/azents/src/azents/core/tools.py
  - python/apps/azents/src/azents/services/google_application/**
  - python/apps/azents/src/azents/services/google_oauth/**
  - python/apps/azents/src/azents/services/google_workspace/**
  - python/apps/azents/src/azents/repos/google_oauth/**
  - python/apps/azents/src/azents/rdb/models/google_oauth.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/google.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/personal_google.py
  - python/apps/azents/src/azents/api/admin/system_setting/v1/google.py
  - python/apps/azents/src/azents/engine/tools/google*.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/d1142f351e96_cut_over_google_workspace_direct_tool_.py
  - typescript/apps/azents-web/src/shared/toolkits/google-*.ts
  - typescript/apps/azents-web/src/shared/toolkits/components/Google*.tsx
  - typescript/apps/azents-web/src/shared/toolkits/containers/useGoogle*.ts
  - typescript/apps/azents-web/src/shared/toolkits/containers/useToolkitFormContainer.ts
  - typescript/apps/azents-web/src/shared/toolkits/toolkit-form-lifecycle.ts
  - typescript/apps/azents-web/src/features/agents/containers/useAgentToolkitManagementContainer.ts
  - typescript/apps/azents-web/src/features/agents/components/ManagedAgentToolkitSection.tsx
  - typescript/apps/azents-web/src/features/toolkits/*Google*.tsx
  - typescript/apps/azents-web/src/features/toolkits/containers/useGoogleCallbackContainer.ts
  - typescript/apps/azents-web/src/trpc/routers/google.ts
  - typescript/apps/azents-admin-web/src/features/system-settings/*Google*.tsx
  - typescript/apps/azents-admin-web/src/features/system-settings/google-application-state.ts
  - typescript/apps/azents-admin-web/src/features/system-settings/components/GoogleApplicationCard.tsx
  - typescript/apps/azents-admin-web/src/features/system-settings/containers/useGoogleApplicationCardContainer.ts
  - testenv/azents/e2e/src/tests/required/public/test_google_connection.py
  - testenv/azents/e2e/src/tests/web/public/test_google_connection.py
last_verified_at: 2026-10-22
spec_version: 1
---

# Google Connection

The `google` provider exposes a closed typed catalog of Gmail, Calendar and Drive
operations using the official Google API Python Client and Google authentication
SDKs. It is distinct from generic MCP, GCP and Google Analytics. Resource requests
use fixed official service hosts; callers cannot supply provider methods, hosts,
paths, authorization headers or arbitrary request bodies.

## Service Selection and Actual Access

Canonical configuration contains `services`, `tool_groups`,
`oauth_request_scopes` and `timeout`. Managers choose service-specific groups
directly or edit the read-only, assistant, full or clear presets. New connections
start without selected groups. The backend-owned closed catalog describes each
group's operations and sufficient SDK method scopes. Connect/reconnect derives
request scopes from selected groups, including internal prerequisites, and removes
only scopes redundant under the compiled policy. Client scope strings are not
authorization authority.

Selected groups are an execution ceiling independent of actual Google grants.
Final review shows the usable count and unavailable operations for every selected
group; partial consent cannot enable an unavailable member. Confirmation may narrow
the reviewed groups but cannot add unreviewed groups. Saved status, reconnect and
publication retain explicit selections. Preset names are not persisted authority.
A local change can enable or disable a service or selected group without reconnecting,
adding authorization, changing the connected account or revoking remote effects.
An empty enabled-service set is valid for a saved connection.

The compiled operation policy maps each typed operation to supported SDK methods
and sufficient scope alternatives. It projects permitted/unavailable tool names,
actual grant evidence and Drive extent separately. Partial grants can publish when
at least one selected group has a durable usable capability. Unknown scope
receipts do not become requested-scope evidence. Broad returned grants never expose
unselected operations.

Drive distinguishes whole-Drive read/write, metadata-only access and Google-limited
app-file access. `drive.file` does not grant arbitrary known-ID access or whole-Drive
search. With mixed whole-read and app-file grants, whole-Drive readability does not
imply whole-Drive writability. Google still enforces per-resource ACLs, protected
resources and app-file eligibility. New Drive write, sharing and ownership groups
request sufficient `drive.file` permission; whole-Drive reads are selected
separately. This does not manufacture whole-Drive write authority or narrow an
existing broader grant.

## Management and Ownership

The creation catalog includes Google only when effective operator client ID,
secret and callback preparation are complete. Filtering the catalog preserves
unrelated providers and saved Google management. Local registration is not a live
service-access probe.

Shared management requires Workspace `TOOLKITS_WRITE`. Agent-owned management
requires the Workspace Owner or the exact active Agent's explicit AgentAdmin.
Personal management requires ordinary membership in the real Workspace and binds
the exact User and initiating Auth Session. It does not require shared-manager
privileges. Candidate identities, callback purposes and target Toolkit ownership
are exact; another Workspace, User or Agent cannot resume or replace them.

Main Web uses the common staged Wizard for Workspace-shared, Agent-owned and
personal Toolkits. Managers choose services, authorize at Google, review the
connected identity and actual full/partial/none/unknown
access, and explicitly publish. Plain Toolkit creation cannot bypass this flow.
Saved metadata edits omit provider configuration and preserve independently saved
service/timeout settings. Reconnect replaces authorization, not unrelated metadata.

The same-context `/oauth/google/callback` removes transient query data and matches
a nonsecret digest to the exact originating attempt. Browser resume stores only
context, deadline, attempt ID, correlation digest, phase and validated return
location, never codes, credentials or OAuth state. Every post-await storage write
and navigation fences the current mounted operation and resume owner. Strict Mode
probing finishes before one-use exchange dispatch.

An uncertain exchange uses review rather than exchanging again. An uncertain
publication permits exact outcome lookup or local cancellation, not automatic
resubmission. Historical outcomes are nonsecret observations and do not prove
current readiness. Disconnect is local and does not promise Google revocation or
reversal of mail, file, calendar or filter effects.

## OAuth and Current Execution Authority

Connect creates an encrypted unpublished attempt with PKCE S256, signed OIDC nonce,
separate callback nonce, exact manager/client generation, request intent and optional
reconnect target. Fresh consent and offline access occur only at manager-started
connect/reconnect. Each candidate needs its own renewal credential. Missing renewal
cannot borrow the old connection's credential.

Exchange claims once before provider I/O, verifies issuer/audience/signature/expiry/
subject/nonce using supported SDKs, and retains actual token receipt omissions.
Post-I/O staging and atomic confirmation repeat manager, client and target fences.
Initial confirm creates Toolkit/grant/owning-Agent namespace atomically. Exact
confirmation replay observes the historical outcome; different settings conflict.
Cancellation, denial and expiry remove only unpublished local credentials.

Runtime authority uses canonical active/running `SessionExecutionOwner`, PostgreSQL
`owner_generation`, Agent/Workspace/root identity, effective Toolkit/source revision,
current client, local service and group selection and actual grants. A manager is not the
execution principal; private and Team runs use the stored connected account.
Personal tools additionally require the User root, current access policy and exact
source admission. Discovery is authorization-filtered; captured handlers repeat
current checks before provider effects and file resolution/publication.

Lazy refresh performs SDK I/O outside database transactions and finalizes under an
exact-current compare-and-set fence. Changed credentials, ownership, client,
services, groups or source authority defeat stale success and failure. Same-current-grant
omissions retain existing renewal/scope evidence. Matching-current credential
rejection marks only that grant reconnect-required. Resource ACL/policy and
transient failures do not globally revoke the connection. Uncertain writes are
never automatically replayed.

Google HTTP failures retain their HTTP status, structured provider status/reasons
and bounded original `error.message` in tool errors. Unknown reasons are retained;
account/resource identifiers, API names and diagnostic console links are retained.
Provider-owned diagnostic text is passed through without masking or substitution,
including credential-like strings. SDK request/URI serialization, headers and
arbitrary response fields are not copied. Malformed
error envelopes retain the generic failure. Compound failures preserve both the
confirmed-step receipt and the provider explanation without replaying any step.

## Typed Workspace Operations

Calendar includes calendar discovery/creation, bounded event search/get, free-busy,
explicit event creation/update/delete and supported event types. Time ranges,
recurrence, status-event properties, notification intent and conference request
identity are validated before dispatch.
Create and update inputs support guest privileges to modify events, invite other
guests and see other guests. Create uses required nullable privilege fields;
null leaves Google's default in effect. Patch omission preserves the saved
privilege, and explicit true/false changes it. Provider-returned privilege values
are retained in event results without inventing defaults for omitted fields.
Google organizer and resource restrictions still apply.

Gmail includes message/thread search and reads, labels and modification, drafts,
new/reply/forward sending and filter lifecycle. Compose inputs distinguish inline
body, authorized body file and attachments; primary-account or verified send-as
identity is checked independently. Reply/forward provenance preserves source/thread
semantics. Applying an existing filter to historical mail changes labels only;
future automatic forwarding remains a persistent Gmail rule. Deleting or locally
disabling a connection does not undo an existing remote filter.

Drive includes metadata/search/link, content read/download/export, blob creation,
folders/copy/content/metadata changes, permissions and supported native imports.
Native format conversion is explicit. Shortcuts have bounded traversal and do not
transfer writability from the readable target. Outputs distinguish confirmed
results, bounded omissions, extraction status and partial multi-step completion.

## Canonical Files and Bounded Content

Inputs accept authorized Exchange/Artifact/current-run VFS resources or absolute
Runner-authorized Runtime paths. A provider HTTP URL or Worker-local file is not a
canonical source. Current resource authority, integrity, total byte limits and
admission are checked before and after reading. Main OAuth credentials remain
server-side and never enter file URLs or model arguments.

Returned bytes become ordinary canonical Artifacts under current Session resource
authority. Publication validates size/hash and source identity. A multi-part failure
reports already completed publications without replaying a Google effect. Runtime
imports and later outbound file operations use the ordinary transfer coordinator
and Runner authority. Runtime-free reads and inline operations remain available;
Runtime paths require a managed Runtime.

Transport, pagination, parser, expansion and inline-output limits are bounded.
Text extraction supports the declared text/PDF/Office formats with truthful
unsupported/failed/truncated status; it does not claim OCR or formula evaluation.
Mail/file/provider content remains untrusted data. There is no Google-specific
security scanner or security acknowledgement gate.

## Picker

Optional operator browser API key and numeric project/app ID enable Picker without
changing OAuth client registration. Shared, Agent and personal managers request a
short-lived token for the exact current connection ID and revision. The server
requires Drive enabled and actual `drive.file` authorization, renews with exactly
that scope, and validates the returned scope, token type and expiry. A broad,
unknown or too-short receipt is rejected. Refresh-token rotation is preserved under
the current fence and requires reconnect before browser delivery.

Picker responses have `Cache-Control: no-store` and `Pragma: no-cache`. The main
credential remains server-side. Picker-only bearer data lives in browser memory
for the active operation and is discarded on completion, cancellation, expiry,
context change or unmount. Selected IDs are transient UI results, not stored grants
or a server-side file allowlist. Picker selection cannot narrow an existing broad
Drive grant; reconnect is required to replace that authorization.

## API and Operator Settings

Shared base is `/toolkit/v1/workspaces/{handle}`; Agent base adds
`/agents/{agent_id}`. Both expose:

- `GET /google/preparation`;
- `POST /google/connect` and `/google/exchange`;
- `GET|DELETE /google/attempts/{attempt_id}`;
- `POST /google/attempts/{attempt_id}/confirm` and `/reconnect-confirm`;
- `GET /google/attempts/{attempt_id}/outcome`;
- `POST /toolkit-configs/{toolkit_id}/google/reconnect`;
- `GET|DELETE /toolkit-configs/{toolkit_id}/google/connection`;
- `PATCH /toolkit-configs/{toolkit_id}/google/services`;
- `POST /toolkit-configs/{toolkit_id}/google/picker-token`.

Personal uses `/personal/google` for staged actions and
`/personal-toolkit-configs/{toolkit_id}/google` for saved actions under the same
Workspace base. Ordinary projections contain no credentials. Callback validation
redacts input values from errors. Service changes require `expected_revision`;
Picker additionally requires `connection_id`.

Admin `GET|PATCH /system-setting/v1/sections/google-oauth` manages redacted local
preparation using optimistic `expected_version` and explicit secret replace/clear.
Environment-owned fields stay read-only. Same-client secret rotation preserves
bindings; a changed client requires reconnect. The setup guide explains ordinary
Workspace APIs, consent, callback, Google verification/restricted-scope obligations
and optional Picker preparation. Configured is not verified live access.

## Stopped Data Cutover

The one-time `d1142f351e96` migration runs only across the stopped application
boundary. Its frozen finite mapping converts old task/config and publication
settings into canonical services/request intent, abandons unpublished candidates
and clears Google-only discovery/deferred snapshots. It preserves encrypted current
grants and historical publication identities. Ambiguous ownership or malformed
rows fail atomically with nonsecret diagnostics. There is no runtime legacy decoder.
After commit, rollback requires the matching operator checkpoint, not a downgrade
that invents old authorization state. No operational migration is implied by local
migration tests.

The stopped `f512e037a843` conversion adds all existing groups for each formerly
enabled service to saved configurations, encrypted setup and nested saved targets,
and published create/reconnect settings. It preserves the previous effective
operation set for every actual grant, rather than inferring capabilities from
requested scopes. Existing credentials, actual grants, connection identities,
revisions and metadata remain unchanged. Pending setup requires the deployment
encryption key and is re-encrypted without changing candidate credentials. A
malformed row or wrong key aborts the transaction with identifier-only diagnostics.
No permanent missing-group runtime fallback is provided; downgrade requires the
pre-migration checkpoint to avoid turning narrow selections into broader authority.

## Verification Limits

Unit, HTTP-route and independent-transaction PostgreSQL tests own scope matrices,
currentness/races, service updates, Picker receipt validation and migration
preservation. Component tests own detailed Wizard, Picker and operator UI states.
Assembled E2E routes official SDK requests to synthetic fixed-host Google
TLS/OAuth/identity/Workspace peers in isolated Docker, with ephemeral trust in API
and Worker. Product hosts, SDK decoding and authorization remain unchanged; the
fixture does not write the product database.

Required E2E verifies partial grants, unpublished review, exact publication,
reconnect cancellation/replacement, historical outcome, disconnect, actual Calendar
read and refresh, and absence of an ungranted write at the provider. Gmail/Drive
E2E verifies allowed Calendar event creation, message read/send, Gmail filter
creation, `drive.file` resource denial, canonical Artifact bytes, real Runner import
and resumable upload with matching SHA-256 through shared Team and personal User
Session sources. The personal flow also verifies minimal Picker issuance, noncacheable
response headers and rejection after revision-fenced local service withdrawal. Browser E2E
verifies same-context callback, partial review, explicit publication and reconnect
metadata preservation on shared and Agent surfaces. Picker browser verification
uses the deployed loader/API and a synthetic modal peer to observe selection,
cancellation, disposal and navigation cleanup without changing the main grant or
persisting credentials/selected IDs.

These are synthetic contract checks, not live Google interoperability, security
certification, quota/load evidence or compliance approval. Live OAuth, real Picker,
restricted-scope review, real account ACLs and Google format conversion remain
external prerequisites. No live Google account, production migration, merge,
deployment or release is claimed.
