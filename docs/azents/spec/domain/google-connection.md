---
title: "Google Connection"
created: 2026-10-14
tags: [google, toolkit, oauth, backend, frontend, engine, security]
spec_type: domain
domain: google-connection
code_paths:
  - python/apps/azents/src/azents/core/google_*.py
  - python/apps/azents/src/azents/core/tools.py
  - python/apps/azents/src/azents/services/google_application/**
  - python/apps/azents/src/azents/services/google_oauth/**
  - python/apps/azents/src/azents/repos/google_oauth/**
  - python/apps/azents/src/azents/rdb/models/google_oauth.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/google.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/personal_google.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/__init__.py
  - python/apps/azents/src/azents/api/admin/system_setting/v1/google.py
  - python/apps/azents/src/azents/engine/tools/google.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/e5bb444eed80_add_google_connection_authority.py
  - typescript/apps/azents-web/src/shared/toolkits/google-*.ts
  - typescript/apps/azents-web/src/shared/toolkits/components/GoogleSetup.tsx
  - typescript/apps/azents-web/src/shared/toolkits/containers/useGoogleSetupContainer.ts
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
last_verified_at: 2026-10-17
spec_version: 1
---

# Google Connection

The `google` provider composes fixed official Calendar, Drive and Gmail MCP
endpoints. It is separate from generic single-server MCP, GCP and Google Analytics.
This Spec covers backend/API execution and the management surfaces. Live Google
interoperability remains distinct from deterministic local verification.

## Management Surfaces

The platform creation catalog (`GET /toolkit/v1/toolkits`), shared by Workspace
and Agent Toolkit selection, includes Google only when effective operator client
ID, secret and deployment callback preparation are complete. Missing, incomplete
or invalid registration hides Google without hiding unrelated providers. Complete
environment-owned registration remains supported. This local availability check
does not assert Preview eligibility or live service access. Saved Google connections
remain queryable and manageable; catalog filtering does not remove their provider
from execution or replace current-grant authorization checks.

Main Web routes Google creation through its unpublished lifecycle rather than
generic Toolkit creation. Managers explicitly select tasks without write defaults,
authorize, then inspect the actual account and full/partial/none/unknown task
permissions. Earlier selections remain available in a disclosure. Task summaries
are localized; exact permitted/unavailable tool identifiers are inspectable in
separate details. Empty usable evidence, missing renewal or an expired attempt
cannot enable publication. Security acknowledgement starts false on each review.

The same setup component supports Workspace-shared, exact Agent and
User-within-Workspace ownership. Personal creation/editing is reached through
`/w/{handle}/personal-tools`; its strict scope, query keys, staged resume and
callback return carry that Workspace handle. Another Workspace's resume cannot
restore the personal draft even for the same User and Toolkit identifier.
Saved Toolkit metadata updates omit Google provider configuration, preserving the
task/timeout settings confirmed independently by reconnect. Task permission changes
use ordinary staged reconnect and reviewed atomic replacement. Agent capabilities
restores only the matching Google create or exact Agent-owned edit surface, including
uncertain-publication recovery. Closing or backing out of staged Google creation
invokes exact local abandonment; successful cleanup can finish after view unmount
only while the stored resume still belongs to that attempt. A publication that wins
that cancellation race remains an inspectable outcome. Local disconnect has
explicit confirmation and does not claim remote revocation or reversal of effects.

The `/oauth/google/callback` page scrubs transient query data and matches a
nonsecret digest to the exact originating attempt before exchange or denial
cancellation. Browser resume stores only exact context, deadline, attempt ID,
correlation digest, phase and validated return destination. It contains no code,
token, secret or OAuth state. The backend's encrypted state remains authoritative.
A stale callback attaches nothing and does not cancel a sibling attempt.
Every post-await callback storage write and navigation checks both the mounted
operation and the exact current resume owner. Leaving or replacing the callback
fences a late exchange/denial result without clearing a newer attempt. Strict Mode
probing finishes before the one-use external exchange is dispatched.

An uncertain exchange is inspected through review without exchanging again. An
uncertain publication offers exact outcome lookup or local cancellation; it does
not automatically authorize, resubmit settings or replay a tool operation.
Outcome lookup alone does not prove cancellation or current readiness.

Admin System Settings has a Google application card with redacted preparation,
environment-owned read-only fields, explicit secret replacement/clear actions,
fixed callback copy and current-version conflict feedback. Saving uses optimistic
versioning. A conflict or uncertain save requires reloading before another mutation;
reloading discards the draft rather than silently merging secret edits. Configured
locally is not labeled verified service access or Preview eligibility.

## Operator Registration and Ownership

The optional `google_oauth` System Settings Section owns one current operator
client and encrypted secret. Only System Admin manages it. Public managers see
redacted local preparation; configuration is not verified Preview/client/service
access. Each published Toolkit owns one verified subject/client-bound grant.

Workspace-shared management requires `TOOLKITS_WRITE`. Agent-owned management
requires the Workspace Owner or exact active Agent's explicit AgentAdmin. Callback
and candidate operations retain exact initiating User/Auth Session/Workspace/
Agent. Manager identity is never the runtime execution principal.

Runtime uses canonical active/running `SessionExecutionOwner` and PostgreSQL
`owner_generation`, current Agent/Workspace/root identity, effective Toolkit
relation/namespace and current grant/client/task evidence. Both private and Team
runs use the stored connected account, never a channel participant's identity.

## OAuth Candidate and Publication

Personal management is available through
`/toolkit/v1/workspaces/{handle}/personal/google` and the Workspace-scoped personal
saved-connection routes. Its User-owned subject requires the real Workspace and
binds the current User and exact initiating Auth Session, with no owning Agent.
Ordinary current membership is required; personal management does not require
shared Toolkit-manager or AgentAdmin authority. Separate personal callback purpose
and exact User/Workspace owner context prevent shared/Agent or other-Workspace
callbacks from changing a personal attempt, including for the same User. The common staged
connect, exchange, review, confirm, outcome, cancellation, reconnect, status and
local disconnect lifecycle remains authoritative.

Personal confirmation publishes the canonical Toolkit and Google grant
atomically with default dynamic `all` access. Reconnect preserves the current
personal access policy and unrelated metadata while applying the existing
grant/client/attempt replacement checks. Personal User ownership is legal in
the staged-attempt schema; existing Workspace/Agent attempt identities and
encrypted payloads are preserved. Personal Web management reuses the common
staged Wizard and saved metadata form in the Workspace's personal surface.

Personal Session execution uses an exact source-bound adapter to the common current
grant/client/task checks. Its canonical User-root association, active owner, ordinary Agent
access, personal policy and source revision are rechecked before discovery, renewal and
calls. Post-renewal publication repeats personal parent admission inside the existing
current-grant CAS operation; withdrawal, source change and changed client evidence defeat
stale success and failure. Shared/Agent delegation behavior remains unchanged.

Connect stores an unpublished encrypted attempt with separate callback-state
nonce, OIDC nonce, PKCE verifier, exact callback/client generation, selected tasks
and optional saved reconnect target. Authorization requests use supported Authlib
APIs, PKCE S256, minimal identity/task scopes and offline access with fresh consent
only at the explicitly manager-started Connect/Reconnect boundary. Each candidate
uses its own returned renewal credential, never a copied saved grant token. Missing
renewal remains unavailable despite the consent request. Encrypted callback
state also binds the exact manager context.

Exchange claims once before SDK/provider I/O. Signed Google identity verification
precedes issuer/audience/expiry/subject/nonce projection. The Google token decoder
retains actual scope and refresh-token absence before SDK normalization. Requested
scope never substitutes for actual grant evidence.

Post-I/O staging rechecks current manager, client generation and attempt/target
state. No Toolkit or grant executes before explicit confirm. Review exposes only
identity, selected tasks, exact permitted/unavailable tools, full/partial/none/
unknown grant evidence, renewal availability and security notice.

Confirm requires at least one durable usable capability, selected tasks within
the reviewed set and fresh strict-boolean security acknowledgement. Initial
publication atomically creates Toolkit/grant and owning-Agent namespace where
applicable. Plain Toolkit CRUD cannot create Google connections.

Published attempt outcomes contain minimal final nonsecret settings and identities,
not candidate/setup ciphertext. Exact replay observes the outcome; different
settings conflict. Outcome lookup does not require the current operator secret
and does not imply current readiness after later replacement/disconnect.

## Ordinary Reconnect and Local Cleanup

Reconnect stages against exact saved connection identity, permission/auth state
and authentication-affecting configuration. Routine access-token renewal retains
identity; unrelated metadata changes are preserved. Reviewed confirmation replaces
the current grant atomically with a new identity, defeating older refreshes and
sibling reconnect targets.

Cancel, denial, expiry and failed verification abandon only local unpublished
credentials. Local cancellation never promises to undo Google consent or provider
effects. Disconnect deletes local current grant and fences pending targets.
A fresh explicit reconnect started after disconnect may publish into the saved
Toolkit after new review; an old cancelled target cannot resurrect it.

Expiry checks delete unpublished ciphertext in a committed operation before
reporting expiry. Start also removes expired unpublished credentials within its
exact initiating context. This is not a user-facing saved-draft/history feature.

## Task and Execution Policy

Eight explicit task groups cover Calendar read/availability/edit, Drive read/
restricted files, and Gmail read/drafts/modification. No task is preselected.
Exact compiled remote names and sufficient scope alternatives intersect current
selection and actual grants. Within-group partial permissions remain visible.
`drive.file` does not grant whole-Drive search. There is no Gmail send tool.

Each service uses a stable Toolkit/service snapshot key. Discovery is asynchronous;
schema snapshots are not authorization. Unsupported root schemas, unknown tools
and flagged schemas are quarantined. Cached schemas are re-filtered against current
grants at projection, and captured handlers repeat exact raw-name admission before
outbound effects. Service-prefixed names avoid collisions.

Lazy renewal uses detached current state, SDK I/O outside DB transactions and
owner-fenced compare-and-set finalization. Changed credentials, current client/
generation, delegation, selection or Session ownership defeat stale success and
failure. Same-current-grant refresh omissions retain existing renewal/scope
evidence; other Toolkit/subject/client credentials are never borrowed.

Definitive matching-token authentication rejection marks only that current grant
reconnect-required. Resource ACL/policy and transient failures are not global
revocation evidence. Google calls are not automatically replayed after uncertain
effects or reconnection.

## Content Inspection

The Google-specific local scanner inspects complete remote tool text/schema,
outgoing argument keys/values and incoming text/structured results before common
extraction/artifact creation. Cached schema text is inspected again. Unknown binary
content is rejected rather than claimed scanned.

Traversal and normalized/decoded views have depth/node/string/total budgets.
Unicode/invisible/percent and explicitly supported base64 inspection detects a
tested known-pattern corpus. Prefix truncation cannot approve uninspected content.
Flagged/uninspectable/inspector-failed arguments cause no Google data operation.
Blocked incoming content publishes no original response/artifact and reports that
the provider effect may already have completed.

Known-pattern screening is not complete prevention. The final notice documents
novel/semantic/obfuscated/multilingual gaps, false positives, false negatives and
inspection limits. Diagnostics never contain blocked payloads or token/secret data.
No paid processor, Model Armor activation, generic scanner plugin or relay exists.

## API

Shared base: `/toolkit/v1/workspaces/{handle}`.
Agent base adds `/agents/{agent_id}`. Both ownership routes provide:

- `GET /google/preparation`;
- `POST /google/connect` and `POST /google/exchange`;
- `GET|DELETE /google/attempts/{attempt_id}` for review/local cancellation;
- `POST /google/attempts/{attempt_id}/confirm` for new publication;
- `POST /google/attempts/{attempt_id}/reconnect-confirm` for saved replacement;
- `GET /google/attempts/{attempt_id}/outcome`;
- `POST /toolkit-configs/{toolkit_id}/google/reconnect`;
- `GET|DELETE /toolkit-configs/{toolkit_id}/google/connection`.

Authorization-input validation removes code/state/body values from diagnostics.
Saved projections contain no tokens and distinguish missing grants, reconnect,
operator configuration and changed-client binding. Admin operator routes are
`GET|PATCH /system-setting/v1/sections/google-oauth`.

## Verification Limits

Deterministic unit, HTTP-route and PostgreSQL tests validate local contracts,
including real independent-transaction confirm/cancel ordering. Assembled-product
E2E uses synthetic fixed-host Google TLS/OAuth/identity/MCP inside the isolated
test Docker network, with ephemeral certificate trust in Public API and Worker
containers. Product URLs, supported SDK verification and authorization remain
unchanged. The fixture does not use a live Google account or write the product DB.

Representative API flows cover partial grants, unpublished review, explicit
acknowledgement, idempotent publication, reconnect cancellation/replacement,
historical outcome and local disconnect. Worker E2E proves SDK refresh, a permitted
Calendar read and absence of the ungranted write at the synthetic provider.
Browser E2E covers same-window/context callback return, partial review and explicit
publication for Workspace-shared and Agent-owned surfaces, ordinary reconnect and
metadata updates that preserve its confirmed timeout. Narrower tests own the
remaining authorization, race, scanner and UI-state matrices.

These checks establish assembled local behavior against a synthetic contract.
Public discovery established endpoint metadata and catalogs, not authenticated permissions.
Live scope-to-tool mapping, endpoint token reuse, Preview/renewal behavior,
screening efficacy/compliance and mixed-version rollback remain conditional.
No live Google account or production change is claimed.
