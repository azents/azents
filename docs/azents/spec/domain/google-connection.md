---
title: "Google Connection Backend"
created: 2026-10-14
tags: [google, toolkit, oauth, backend, engine, security]
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
  - python/apps/azents/src/azents/api/admin/system_setting/v1/google.py
  - python/apps/azents/src/azents/engine/tools/google.py
  - python/apps/azents/src/azents/engine/tools/deps.py
  - python/apps/azents/db-schemas/rdb/migrations/versions/e5bb444eed80_add_google_connection_authority.py
last_verified_at: 2026-10-14
spec_version: 1
---

# Google Connection Backend

The `google` provider composes fixed official Calendar, Drive and Gmail MCP
endpoints. It is separate from generic single-server MCP, GCP and Google Analytics.
This Spec covers the implemented backend/API and execution path, not an existing
browser setup surface. The Google browser flow is a later delivery phase.

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
including real independent-transaction confirm/cancel ordering. Public discovery
established endpoint metadata and catalogs, not authenticated permissions.
Live scope-to-tool mapping, endpoint token reuse, Preview/renewal behavior,
screening efficacy/compliance and mixed-version rollback remain conditional.
No live Google account or production change is claimed.
