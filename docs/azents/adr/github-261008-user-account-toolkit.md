---
title: "GitHub User Account Toolkit Technical Decisions"
created: 2026-10-08
document_role: primary
document_type: adr
snapshot_id: github-261008
tags: [github, toolkit, oauth, architecture, security]
---

# GitHub User Account Toolkit Technical Decisions

- Snapshot: `github-261008`
- Requirements: [github-261008/REQ](../requirements/github-261008-user-account-toolkit.md)
- Mode: Collaborative; the requester owns unresolved material technical decisions.
- Toolkit-local ownership and non-expiring user tokens remain ADR-D1 and ADR-D2. ADR-D4 governs current fail-open single-token cleanup and supersedes ADR-D3's completion/retry policy. Implementation is authorized for the current scoped Design; merge and deployment are separate.

## Current-System Framing

Baseline main: `279db5f1fb52c634570d3d5eff6a669d2becdfd3`, refreshed before evaluating UI integration. The previous investigation used `beedc9089`; the new baseline changes Toolkit presentation and mutation flow but does not implement GitHub user-account credentials.

### Existing Authority and Ownership

- `ToolkitConfig` is Workspace-shared or owned by one saved Agent. Existing management authorization, Agent participation, and scope remain authoritative.
- GitHub credentials distinguish PAT, BYOA installation, and Platform installation. A Platform Toolkit retains server-resolved App identity and installation targets; BYOA retains provided App ID/private key and installation targets.
- Existing Platform OAuth discovers and synchronizes a user's accessible installations, then revokes the temporary token. Runtime execution issues installation tokens using App JWT authority. This discovery flow remains necessary for existing App mode.
- GitHub tools use installation-aware MCP bindings; optional Git/gh environment exposure is explicitly opt-in, with per-installation variables and a default-installation selector for App mode.
- MCP OAuth stores one encrypted connection per Toolkit, whereas GitHub has no durable user-account connection. Its finalization logic alone does not serialize external consumption of a one-use refresh token.
- Credentials are encrypted through `CredentialCipher`; Public and Worker consumers use layered services and repository-owned completed transactions. External provider or Runtime I/O does not occur inside a database transaction. Redis is optional.

### Current UI Baseline

- `ManagedAgentToolkitSection.tsx` renders compact identity/readiness cards and a details modal. Add uses a catalog with new-connection and Workspace-connection tabs, followed by create/edit views.
- `useAgentToolkitManagementContainer.ts` separates catalog/detail/edit state and keeps successful Toolkit mutations independent of the parent Agent save.
- `toolkit-detail-projection.ts` renders only allowlisted returned configuration/connection fields; it does not introspect grants remotely or expose secrets.
- `useToolkitFormContainer.ts` and `GithubConfigFields.tsx` remain the provider form boundary. Current GitHub authorization is not supported by the generic direct-authorize predicate in `agentToolkitManagementState.ts`.
- New account identity and multi-organization readiness belong in returned GitHub connection summaries/details rather than fabricating generic OAuth scopes or displaying raw credentials.
- When the Platform App is absent, GitHub remains in the catalog for PAT/BYOA. Only Platform authentication choices are omitted. Saved Platform connections remain explainable in details.

### Gaps to the Requirements

1. No persistent GitHub user token, verified execution-account identity, or Toolkit-local user connection exists (`REQ-1`, `REQ-2`, `REQ-8`). Refresh metadata and a renewal owner are not required by the selected non-expiring scope.
2. BYOA credentials have no OAuth client configuration/callback lifecycle (`REQ-13`).
3. Existing user installation discovery is first-page only and provides no account/repository preparation summary for new user authority (`REQ-3`, `REQ-4`, `REQ-6`).
4. Existing OAuth callbacks and Toolkit mutations do not implement the durable user-account candidate/replacement lifecycle required by `REQ-7` and `REQ-9`.
5. Current installation-token Runtime cache is not the source of truth for a new user connection. User-mode execution must load the current saved connection so replacement/disconnection is respected; no periodic user-token rotation occurs (`REQ-8`, `REQ-10`).
6. Existing Public setup routes return missing-platform errors when invoked; the new choice-availability contract must let forms hide unconfigured choices without calling Admin APIs (`REQ-12`).
7. Existing validation fixtures cover App/OAuth registration checks rather than successful non-expiring user delegation, expiring-response rejection, or multi-org account authority (`REQ-11`).

## Fixed and Derived Outcomes — Not New Choices

- User authority is the OAuth-connected account's and selected App's intersection, not a participant-relative credential (`REQ-2`, `REQ-4`).
- Platform and BYOA each support user and installation modes; PAT and existing modes remain unchanged (`REQ-1`, `REQ-13`).
- Personal plus multiple organizations are simultaneously accessible where the same selected App and connected account have access (`REQ-3`).
- No new contributor-offboarding cutoff; real provider failures and existing Azents management/participation boundaries apply (Requirements Fixed Constraints).
- User mode uses non-expiring tokens without refresh. Unauthorized replacement, silent fallback, secret disclosure, and automatic migration are prohibited (`REQ-7` through `REQ-10`).
- New user connections cannot be implemented by simply retaining the temporary discovery token while omitting account verification, non-expiring response validation, and setup binding.
- Agent Runtime raw-credential use remains optional and risk-disclosed. Immediate recall of in-flight credentials is not assumed (`REQ-9`, `REQ-10`).
- Current catalog/details/modal and immediate save semantics remain the UI host. Toolkit creation is not proof of completed provider authorization (Requirements Fixed Constraints).
- No new token schema version/epoch, generic credential hub, relay proxy, Runtime authentication mode, webhook ingress, or scheduler actor is authorized merely by this decision briefing.

## Material Technical Decision Map

- [x] TD-1 — **Accepted:** Toolkit-local credential and renewal ownership, recorded as `github-261008/ADR-D1`. Multiple Agents reuse one shared Toolkit; distinct Toolkits do not automatically reuse saved tokens.
- [x] TD-2 — **Closed by scope:** the requester selected non-expiring user tokens, recorded as ADR-D2. No refresh ownership, rotation claim, or periodic renewal service is introduced.
- [x] TD-3 — **Derived:** without user-token rotation, use the Toolkit-local current token through existing MCP and explicitly enabled Runtime credential boundaries. Retain accurate in-flight/process cessation limits under REQ-9/REQ-10; no new proxy/gateway or background credential service.
- [x] TD-4 — **Accepted:** single-token GitHub revocation on new user-mode cleanup, recorded as ADR-D3 after the requester rejected local-only removal. The exploratory brief below is retained as history, not current authority.

The renewed Requirements and ADR-D2 remove the two rotation-specific lanes. Existing Runtime opt-in and cessation limits remain authoritative. Any new user-visible policy returns to Requirements; ordinary equivalent helper/API naming and file layout remain agent-owned. New material mechanisms discovered during feasibility checks require another ADR decision rather than being inferred from this map.

## TD-1 Brief: Credential Ownership Across Toolkits

Affected requirements: `github-261008/REQ-2`, `REQ-7`, `REQ-8`, `REQ-9`, `REQ-13`.

### Consequence-Level Question

When the same GitHub account is connected using the same App to Toolkit A and Toolkit B, should the two Toolkits keep distinct OAuth token/renewal lifetimes, or should their tokens be backed by one internal App/account credential lifetime?

### Option 1: Toolkit-Local Token Lifetime

Each Toolkit receives its own OAuth result and owns its encrypted token/renewal state. Sharing one Toolkit among several Agents still shares one renewal owner. Separate Toolkits do not automatically reuse each other's saved token material.

- Matches existing Toolkit-level credential ownership and the absence of a general personal credential hub.
- Local disconnect/reconnect affects that Toolkit and its consumers rather than silently replacing another Toolkit's saved tokens.
- Reusing the same account in another Toolkit may require another authorization round; provider-grant rules or issuance limits still apply and must not be represented as guaranteed provider-side isolation.
- BYOA client configuration remains scoped to the provided App connection; credential sharing across unrelated Workspaces is unnecessary.
- GitHub-wide grant revocation or App installation changes can still affect multiple independently stored connections. Per-Toolkit storage does not change those external facts.

### Option 2: Internal App/Account Credential Backing

Toolkits retain local use scopes but reference a shared provider-account credential that owns tokens and renewal. This need not expose a global credential-hub UI, but it is a distinct source-of-truth and lifetime model.

- Fewer token copies and one renewal owner when many Toolkits intentionally use the same provider account.
- Requires a reuse/ownership boundary, reference lifetime, compatible BYOA client configuration, and atomic attachment/reconnection rules.
- Reauthorization of the shared backing replaces tokens used by multiple Toolkits. Local detach/disconnect must not revoke shared credentials needed by remaining references.
- The design must prevent hidden credential reuse across authorization or Workspace boundaries and explain the actual reconnection impact while satisfying `REQ-9`.

### Recommendation and Evidence Limits

Recommend Option 1 for this feature: keep the new credential lifecycle within the existing Toolkit boundary. Reusing a Workspace-shared Toolkit already enables multiple Agents to share one connection, so a second shared provider-account aggregate is not needed to satisfy B or multi-org access.

Option 1 was subsequently accepted as ADR-D1. Individual token issuance and token-specific revocation behavior still need provider/fixture validation; installation selection does not itself narrow a user token's permission range. The final design must not infer unrelated OAuth-App token issuance limits as GitHub-App facts.

## Withdrawn TD-2 Brief: Exclusive Renewal and Indeterminate Rotation

The following unaccepted options were explored while expiring credentials were an assumption. They are retained as exploratory provenance only and are not part of the current Design, implementation scope, or approved state. ADR-D2 closes this lane.

Affected authority: ADR-D1 and `github-261008/REQ-7`, `REQ-8`, `REQ-9`, `REQ-10`; repository-only database transactions and Redis-optional conventions.

### Fixed Safety Outcomes

Renewal must be serialized before the external refresh call, not merely when writing its result. One shared Toolkit can be used by multiple Agents/processes. An ordinary in-process mutex or final compare-after-HTTP is insufficient. Token publication must reject a result for a disconnected/replaced connection. Provider HTTP must run outside an active database transaction.

GitHub documents that successful refresh invalidates both preceding tokens. No supported response-recovery or idempotency facility was found for refresh. If provider rotation succeeds and the response is lost before durable publication, the server cannot recreate that returned pair from the old token. Indefinite retries cannot create an exactly-once protocol and may use already-consumed credentials. Unrecoverable ambiguity requires an authentication error/reauthorization boundary under REQ-8, not fallback to App credentials.

### Option 1: Persisted Exclusive Renewal Ownership

A short completed DB operation records one renewal owner for the current Toolkit connection before HTTP. It records enough in-flight identity to let other consumers recognize an existing operation and to guard its later publication. External refresh runs outside transactions; a second completed operation publishes the pair only if the exact operation still owns the unchanged connection. No schema-version or token-epoch feature is implied.

- Coordinates across Workers through PostgreSQL, without Redis or a DB connection pinned during provider latency.
- Competing consumers reread the committed result rather than issue the same refresh token. An abandoned/indeterminate external operation is not treated as authorization to automatically reconsume the old token.
- Process cancellation, HTTP timeout, publication failure, disconnect, and account replacement need explicit operation-state cleanup and failure tests.
- Adds durable transient renewal state. Bounded waiting/ownership lifetimes and conservative reauthorization after an unrecoverable consumed response are material consequences of this choice.
- Late responses must not restore a disconnected/replaced credential. A complete Design will specify exact ownership conditions and safe token-specific cleanup where supported.

### Option 2: Dedicated Database-Session Mutex

Use a dedicated PostgreSQL session-level mutex per Toolkit renewal while provider HTTP executes, with no active SQL transaction. Recheck connection/token state once the mutex is acquired and publish through completed DB operations. Release the mutex and dedicated connection on exit; never use a transaction row lock around the HTTP call.

- Avoids a persisted normal-operation claim but pins a DB connection for provider I/O and requires repository-owned dedicated connection lifecycle outside the current ordinary session factory pattern.
- The production code inspected does not already use this autocommit session-lock pattern; it would need bounded acquisition, cancellation, pool-safe unlock, and DB-session loss checks.
- Mutex disappearance does not record whether GitHub consumed a token. A successor may discover invalid credentials while the prior provider call/result is unknown; conservative failure/reconnection and publication guards are still required.
- A DB-session failure can release exclusivity while an HTTP operation is in flight. The mechanism must fail closed and demonstrate that late results, competing refreshes, and disconnect/reconnect do not corrupt the persisted connection. This is a feasibility condition, not an existing guarantee.

### Recommendation and Validation Scope

Recommend Option 1. It aligns with current completed repository operations, avoids keeping a database connection occupied across external I/O, and retains explicit evidence of a consumed-token uncertainty rather than relying only on a disappearing mutex.

Required evidence for the selected mechanism: one provider refresh under two concurrent Agent consumers; safe reconnect/disconnect during refresh; process/HTTP failure before and after provider consumption; lost publication and late response; retained App/PAT/BYOA-installation paths; no provider request inside a transaction; and no secret payload in diagnostics. Crash testing is not claimed complete by this briefing.

Neither renewal option was accepted. Both are excluded from the selected non-expiring user-connection scope.

## Provider and SDK Feasibility Evidence

- GitHub documents user-token authority across accessible installations and repositories and the App/user permission intersection.
- With expiring user tokens, refresh yields a new token pair and invalidates both the previous access and refresh token. A post-HTTP DB comparison alone cannot prevent duplicate external consumption.
- Configured `githubkit[auth-app]==0.16.1` exposes public OAuth refresh and token/expiry attributes. Cached package metadata/source were inspected; live GitHub exchanges were not performed.
- The current Web exchange signature supports callback URI but no PKCE verifier argument in that version. The supported SDK path or a bounded SDK upgrade needs validation before claiming PKCE feasibility. No manual provider transport exception has been accepted.

Sources:

- https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app
- https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/refreshing-user-access-tokens

## Retained and Replacement Boundaries for Future Design

Retain the existing installation discovery/revocation path, App/BYOA/PAT execution modes, System Settings ownership, multi-installation routing, and current catalog/details structure. Add a distinct persistent user-account setup/runtime path; do not change existing temporary OAuth cleanup semantics globally.

Expected extensions are encrypted GitHub user-connection persistence, typed provider ingress with non-expiring validation, authorized setup/summary/replacement/disconnect contracts, public client generation, provider-form and detail projection extensions, current-connection runtime lookup, and deterministic OAuth/multi-org/replacement fixtures. There is no renewal claim or rotation fixture in current scope.

## Agent-Owned Local Details

Names, equivalent helper boundaries, file organization, fixture values, locale-key names, component composition inside the existing UI host, and equivalent schema shapes may be selected during Design without a new interview when they create no new authoritative state, public policy, execution mode, or lifecycle boundary.

## Accepted Decisions

### ADR-D1. Toolkit-local OAuth credential lifetime

- Authority: `github-261008/REQ-2`, `REQ-7`, `REQ-8`, `REQ-9`, `REQ-13`.
- Decision owner: requester.
- Accepted on: 2026-10-08.

**Decision**

Each GitHub user-account Toolkit owns its OAuth credential and renewal lifetime. A Workspace-shared Toolkit may serve multiple Agents; those consumers share that Toolkit's credential and renewal state. Independent Toolkit configurations do not implicitly share an internal App/account token aggregate. Apply the same boundary to Platform and BYOA user-account connections.

**Rationale**

This preserves the existing Toolkit delegation boundary and uses existing shared attachment for multi-Agent reuse. It limits local account replacement and disconnection impact to the Toolkit being managed without requiring a second credential-ownership layer.

**Rejected alternative**

An internally shared App/account credential backing referenced by multiple independent Toolkits is not introduced in this snapshot. It would create additional reuse, attachment, renewal, and local-versus-provider revocation boundaries without being necessary for the approved B/multi-org scenario.

**Consequences and limitations**

Distinct Toolkits may need separate OAuth exchanges. GitHub grant-wide revocation and installation changes remain external shared influences; independent persistence is not a claim of provider-grant isolation. One Toolkit's publication/renewal must not overwrite a different Toolkit's connection. Serialization, indeterminate rotation recovery, and Runtime freshness remain TD-2/TD-3 and are not accepted by this ownership decision.

### ADR-D2. Non-expiring GitHub App user tokens

- Authority: revised `github-261008/REQ-8`, `REQ-11`, `REQ-13` and requester selection.
- Decision owner: requester.
- Accepted on: 2026-10-08.

**Decision**

New Platform and BYOA user-account connections accept only non-expiring GitHub App user access tokens. Operators/App owners opt out of user-to-server token expiration in GitHub. Authorization does not request `offline_access`. Validate the actual returned token envelope before activating it: a response declaring scheduled expiration or refresh credentials is incompatible and receives configuration guidance, not a silently stored expiring connection.

Store the accepted access token encrypted under the Toolkit-local boundary selected by ADR-D1. Do not store refresh-token material for this feature or implement refresh ownership, a rotation lease, renewal scheduling, or a new token-version/epoch mechanism.

**Rationale and rejected alternatives**

The requester chose non-expiring user connections to avoid periodic rotation and its reconnect/concurrency complexity. Expiring-user-token support and its proposed persisted-claim/session-mutex alternatives are excluded from this snapshot. Existing App-installation token reissuance and unrelated OAuth integrations are unchanged.

**Consequences and risks**

Compromise of a non-expiring token has no scheduled expiration boundary; protect it through existing encryption, non-disclosure, management authority, and optional Runtime exposure controls. Non-expiring does not mean irrevocable: user grant revocation, installation/permission changes, provider policy and authorization failure still apply. Definitive account authentication failure offers reauthorization; transient errors and repo-specific denials must not delete the entire connection.

An App with expiration still enabled cannot produce a supported new user connection merely because Platform registration exists or BYOA client credentials are syntactically valid. Setup must report the mismatch without replacing a working saved connection. No production App settings are changed by this ADR.

**Effect on ADR-D1**

ADR-D1's Toolkit-local ownership remains accepted. Its references to renewal define the rejected expiring-token hypothesis rather than current scope; this new decision removes renewal mechanisms without changing ownership or silently sharing tokens across Toolkits.

## Final Audit Addendum — 2026-10-08

### Updated SDK Feasibility Evidence

The earlier high-level exchange-signature limitation was resolved by a runtime-only probe of GitHubKit 0.16.1's public `GitHub.arequest` transport. A MockTransport fixture observed one exchange carrying S256 PKCE's `code_verifier` and the exact callback URI, with retry/cache disabled and a preserved non-expiring token envelope. No SDK upgrade, private API or direct-provider HTTP exception is needed. This is mocked transport feasibility, not live GitHub or product-flow evidence.

### TD-4 Brief: Local Cleanup Versus Provider Token Revocation

Affected authority: `github-261008/REQ-7`, `REQ-9`, `REQ-10`, ADR-D1 and ADR-D2.

**Question:** Should new user-mode cancellation, replacement and disconnection automatically revoke the corresponding GitHub token, or only end Azents's local authorization and remove its stored credential material?

**Option 1 — Local-only cleanup (recommended)**

Remove the local active/candidate credential and prevent future server-authorized resolutions. Do not automatically call GitHub token or grant revocation. This keeps the current feature bounded and avoids invalidating another Toolkit if provider token material is reused. A token copied into a Runtime process or elsewhere may remain valid until provider revocation; local disconnection must explicitly disclose that boundary.

**Option 2 — Automatic single-token cleanup**

Call GitHub's single-token deletion endpoint, never the grant deletion endpoint. This reduces the residual validity of abandoned or disconnected credentials. It requires a proven noninterference mechanism for still-referenced token material, including concurrent setup/publication. Per-Toolkit storage and a pre-request reference check do not themselves prove provider-token isolation.

**Evidence and limitations**

GitHub documents `DELETE /applications/{client_id}/token` as revoking a single token for an OAuth or GitHub App, while deleting an App authorization deletes all associated user tokens. The reviewed documentation does not establish an issuance-isolation guarantee for every separate or concurrent OAuth exchange. This is an unverified assumption, not evidence that GitHub actually returns repeated tokens.

Source: https://docs.github.com/en/rest/apps/oauth-applications#delete-an-app-token

**State:** requester decision pending. Neither recommendation nor SDK/provider feasibility grants implementation authority. Existing installation-mode temporary-token revocation remains unchanged.

### ADR-D3. Revoke retired user tokens at GitHub

- Authority: clarified `github-261008/REQ-9`, `REQ-7`, `REQ-10` and explicit requester selection.
- Decision owner: requester.
- Accepted on: 2026-10-08.

**Decision**

Disconnect/delete revokes the affected user token at GitHub. Confirmed replacement revokes the superseded token; cancellation, rejected activation and discarded setup revoke any issued candidate token. Use the supported single-token deletion endpoint through public GitHubKit operations. Do not delete the App/user grant, uninstall the App, or revoke a newer connection by substituting its token for the captured retired token.

Stop local execution authority before provider cleanup. Run provider HTTP outside DB transactions. Report provider failures and retain the minimum encrypted cleanup material until revocation is confirmed; that material is not an execution credential. Recovery uses an authorized retry of the cleanup operation, not a refresh scheduler or a global credential service.

**Rationale and rejected alternative**

Leaving a non-expiring token valid after its local purpose ends is not the selected security outcome. The earlier local-only recommendation was based on an unobserved token-reuse hypothesis and is rejected. Provider behavior must be verified with appropriate evidence; an unverified possibility cannot silently relax the revocation requirement.

**Consequences and limits**

The existing temporary installation-discovery cleanup is unchanged. Its best-effort, log-only helper is not sufficient to report successful persistent-user cleanup: the new path must expose failure and preserve retry material.

Provider-confirmed revocation prevents subsequent authentication with the token, including copied credentials; it does not erase copies, undo completed actions, or guarantee cancellation of a request GitHub already admitted. A lost response or unavailable provider remains an incomplete operation until cleanup can be confirmed. Actual unexpected provider token reuse is an evidence-driven compatibility issue to report, not authority for a default no-revocation path or speculative shared-token machinery.

**Effect on the TD-4 brief**

This accepted decision supersedes the brief's pending state and local-only recommendation. TD-4 is resolved; full Design approval remains separate.

### ADR-D4. Fail-open token cleanup

- Authority: requester-revised `github-261008/REQ-9`, retained REQ-7/REQ-10 and explicit implementation correction.
- Decision owner: requester.
- Accepted on: 2026-10-08.

**Decision**

Attempt the affected token's revocation through the supported single-token GitHub API outside database transactions, with a short bounded wait. If the provider call fails, log a sanitized warning and complete the local disconnect, replacement, cancellation or deletion. Do not restore the old credential, substitute another execution authority, or claim provider revocation succeeded.

Remove durable cleanup records/status, manager cleanup retry APIs/UI, proof-of-invalidity probes used only to confirm cleanup, cleanup-based parent deletion barriers and dedicated exchange-completion machinery introduced to guarantee cleanup. Keep context binding, one-use OAuth claim, staged confirmation, current-row registration protection, encryption for active/candidate credentials and actual authentication failure handling.

**Rationale and rejected alternatives**

The requester explicitly chose the simpler fail-open failure policy. The intervening fire-and-forget proposal was withdrawn: the normal operation still attempts bounded revocation, but cleanup failure is not an availability or deletion gate. ADR-D3's encrypted failed-cleanup retention and explicit retry path are no longer required.

**Consequences**

A non-expiring token may remain valid at GitHub after failed cleanup, including a copied credential. Azents stops local credential use and removes its local state regardless; later server-managed Toolkit resolutions cannot obtain that retired credential. Process cancellation or a result never received cannot guarantee provider revocation. No background retry, actor, global credential hub, grant-wide revocation or App uninstall is introduced.

This is fail-open cleanup, not fail-open authentication. Invalid OAuth/context/account authority still fails; transient provider errors during ordinary use do not authorize another account, PAT or installation fallback.
