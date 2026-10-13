---
title: "Google Service Connection Design"
created: 2026-10-13
document_role: primary
document_type: design
snapshot_id: google-261013
tags: [google, toolkit, oauth, architecture, security, frontend, testing]
---

# Google Service Connection Design

- Snapshot: `google-261013`; reference: `google-261013/DESIGN`.
- Scope authority: [google-261013/REQ](../requirements/google-261013-connection.md).
- Material decision map: [google-261013/ADR](../adr/google-261013-connection.md).
- Revision: `1`; independent implementation contracts are drafted below.
- This is an unapproved primary draft, not a complete implementation authorization.
  D1–D4 remain pending. Their proposed realizations are isolated from the authority
  table; placeholders identify the exact affected contracts.
- No code, migration, Google consent, or deployment has been performed.

## Current System and Gap

| Current evidence | Gap to this snapshot |
| --- | --- |
| Generic MCP has one `server_url` and one OAuth row per Toolkit | Named Google services need provider-specific routing, not a generic multi-server migration |
| Generic OAuth stores requested `scope`; `OAuthTokenResponse` omits granted scope | Partial consent requires independently verified grant evidence |
| MCP snapshots store remote schemas and survive discovery outages | Google must filter both projections and calls using current capability evidence |
| GitHub user creation retains encrypted unpublished attempts and publishes on confirm | Reusable lifecycle pattern; Google-specific identity and scopes must be validated |
| System Settings separates operator secrets from public status and fences effective configuration | Reusable facilities; Google's chosen registration binding is pending D1 |
| Toolkit resolution retains exact Agent/shared ownership and Team owner checks | Google must use the same authority, not channel-participant identity |

Repository baseline for this design research:
`210f4f0be2065f1ecf3f0c8bca952c8d8216d1a4`. Supporting public probes and limitations
are preserved in the [technical analysis](google-connection-technical-analysis-2026-10-13.md).
Current behavior sources are [Toolkit](../spec/domain/toolkit.md),
[MCP OAuth](../spec/flow/mcp-oauth.md), and
[System Settings](../spec/domain/system-settings.md).

## Architecture and Ownership

```mermaid
flowchart TB
    Operator[Operator registration authority] --> Setup[Google setup service]
    Manager[Exact authorized manager] --> Setup
    Setup --> Candidate[Unpublished encrypted candidate]
    Candidate --> Review[Actual identity and capability review]
    Review --> Publish[Atomic Toolkit publication]
    Publish --> Toolkit[Current Toolkit and grant authority]
    Toolkit --> Filter[Selected and permitted tool projection]
    Snapshot[Per-service MCP schema snapshots] --> Filter
    Filter --> Guard[Current execution authority check]
    Guard --> Calendar[Official Calendar MCP]
    Guard --> Drive[Official Drive MCP]
    Guard --> Gmail[Official Gmail MCP]
```

The diagram does not resolve registration storage, account cardinality, or saved
reconnect eligibility. Those are D1–D3. It describes authority boundaries common
to either admitted outcome.

### Responsibilities

- The backend Google setup domain owns authorization attempts, evidence, review,
  publication, and redacted recovery projections.
- PostgreSQL owns correctness. Redis, browser session state, process caches,
  invalidation events, and MCP snapshots are not credential authorities.
- The operator owns their Google application; Toolkit managers cannot gain
  operator-secret read/write authority by starting setup.
- An unpublished candidate is not a Toolkit attachment or runtime credential.
- A published Google Toolkit uses current Agent-only/Workspace-shared ownership,
  management, enabled state, attachment, and namespace reservation.
- The Google execution provider composes the existing MCP transport and tool
  wrapper. It does not add another credential broker or Runtime dependency.

### Fixed Service Routing

| Service | Compiled MCP endpoint |
| --- | --- |
| Calendar | `https://calendarmcp.googleapis.com/mcp/v1` |
| Drive | `https://drivemcp.googleapis.com/mcp/v1` |
| Gmail | `https://gmailmcp.googleapis.com/mcp/v1` |

Managers cannot substitute arbitrary endpoints through this provider. Existing
generic MCP retains its endpoint/configuration contract. Google Analytics and GCP
remain different Toolkit types. Transport setup, proxy routing, cancellation, and
typed failures continue using the existing MCP client.

## Data and Source of Truth

The following are logical records, not an approved choice of physical schema or
account cardinality. Implementation can choose equivalent typed layout once the
pending binding/reconnect contracts are settled.

| Logical unit | Required data | Lifetime and access |
| --- | --- | --- |
| Setup attempt | Exact initiator/auth Session, immutable Workspace/Agent context, requested task selection, attempted client binding, redirect, encrypted PKCE/nonce, deadline, one-use phase | Unpublished; only exact current authorized setup context can operate |
| Verified candidate | Trusted subject evidence, redacted account display, encrypted tokens/expiry, requested and granted scopes, verification state, per-service observations | Belongs to one attempt; never executable |
| Published grant authority | Toolkit relation, verified subject/client binding, encrypted tokens, current proved scopes, expiry/auth state | Lives with the published Toolkit; no cross-Toolkit token pooling |
| Service observation | Endpoint identity, discovered schema reference, capability checks and sanitized failure reason tied to exact grant/configuration | Evidence only; cannot supply or restore permission |
| Publication outcome | Exact accepted attempt/result and published Toolkit identity | Enables confirm-result lookup after lost response without duplicate creation |

Scope evidence is a discriminated result: `verified(scopes)`, `unknown(reason)`, or
`invalid(reason)`. A verified empty set is distinct from absent/malformed evidence.
Raw provider payloads are decoded into typed responses at ingress and not stored
as an unbounded evidence blob. Remote contents are not ordinary diagnostics.

Tokens and PKCE are encrypted using existing credential/state facilities and
excluded from repr, logs, model context, and management responses. Attempt
abandonment removes unpublished ciphertext. Minimal publication outcome data is
not a product draft/version-history feature.

**Pending D1:** registration source and retirement policy.
**Pending D2:** one or several grant relations and identity review projection.
**Pending D3:** target saved-state comparison and eligibility during reconnect.
There is no provisional implementation of both options.

## OAuth Attempt and Callback Contract

The provider uses a stable deployment callback, proposed as
`{web_url}/oauth/google/callback`, registered exactly with Google. It does not encode
arbitrary Workspace/Agent destinations in a browser-supplied redirect.

1. Check current active User/Auth Session and exact management authority. Capture
   immutable Workspace identity and exact Agent ownership where applicable.
2. Resolve operator preparation, chosen client binding, and task-derived requested
   scopes. Configuration absence blocks consent start but not unrelated Toolkits.
3. Persist an unpublished attempt with encrypted PKCE S256 and nonce/state context.
   The authorization URL is SDK-owned and returns no token or client secret.
4. On callback, authenticate the returning initiator and verify exact context,
   encrypted state, one-use phase, deadline, redirect, nonce, and attempted client.
   Current write authority is checked again; a browser-selected context cannot
   redirect credentials into another Agent or Workspace.
5. Claim the attempt in a completed repository operation. Close its transaction
   before authorization-code exchange. Duplicate callbacks cannot exchange again.
6. Use supported Authlib APIs and the existing HTTP/proxy adapter. Verify Google
   identity with supported Google identity APIs: issuer, audience, expiry, nonce,
   and stable subject. Browser email and `login_hint` are never proof.
7. Decode authoritative granted-scope evidence separately from requested scope.
   Recheck initiating authority, exact claimed attempt, configuration, and expiry
   after provider I/O before storing the verified candidate.
8. Return redacted review state. A callback cannot publish or attach a Toolkit.

Identity scopes are limited to verified principal evidence and explained separately
from Calendar/Drive/Gmail task access. Offline renewal is required for a durable
connection. Missing renewal or scope evidence is not labeled fully ready.

Google may omit a refresh token on later exchanges. Retention is permitted only
where exact same subject/client/grant evidence and the approved lifecycle justify
it. Never borrow a refresh token from another connection. Omitted grant scope must
follow verified provider semantics; requested scopes cannot substitute for it.

An exchange timeout after attempt consumption is uncertain, not proven denial.
Return a normalized verification failure/unknown state and require an explicit
retry path; do not replay the code exchange invisibly. Late responses to cancelled,
expired, replaced, or no-longer-authorized attempts cannot finalize.

## Candidate Lifecycle and Initial Publication

```mermaid
stateDiagram-v2
    [*] --> Preparing
    Preparing --> Authorizing: Explicit connect
    Authorizing --> Verifying: Exact callback claim
    Verifying --> Reviewing: Verified usable result
    Verifying --> Unavailable: Empty or unknown evidence
    Verifying --> Failed: Rejected verification
    Reviewing --> Published: Explicit final confirm
    Reviewing --> Abandoned: Cancel or reset
    Authorizing --> Abandoned: Cancel or expiry
    Verifying --> Abandoned: Cancel or expiry
    Unavailable --> Preparing: Explicit retry
    Failed --> Preparing: Explicit retry
    Abandoned --> [*]
```

Partial consent is data in `Reviewing`, not an instruction to reauthorize.
`Unavailable` distinguishes verified zero capabilities from unknown evidence.
Provider denial, organization policy, transport errors, and missing grants have
separate reasons and next actions.

Review includes actual account evidence, selected permitted tasks, unavailable or
unknown work, operator application identity, and exact Agent/shared context.
Shared review warns that all authorized runs use this connected account.

Initial confirm composes, in one repository-owned transaction:

- current manager authority and exact active ownership context;
- current candidate/attempt phase, deadline, client binding, and reviewed result;
- final selected work bounded by that result, with at least one usable capability;
- Toolkit creation, encrypted grant relation, enabled configuration, and existing
  namespace/attachment obligations;
- exact attempt consumption and publication outcome.

A duplicate confirm returns the exact published outcome under current authority.
A lost response triggers outcome inspection, not another Toolkit or provider
write. A confirm/cancel race has one durable winner; a cancelled result cannot
publish, while a committed publication is not reported as a proven cancellation.
Ordinary metadata changes need not repeat consent. Authentication-affecting edits
invalidate dependent evidence; narrowing selected work cannot enlarge authority.

Candidate TTL is a bounded internal resource/safety limit following the existing
authorization-attempt pattern; its concrete duration is agent-owned if it does not
create a new user-visible persistence guarantee. Expiry cleanup deletes secrets
and cannot remotely revoke another grant.

## Capability Policy and Tool Projection

For each supported task the compiled policy records exact service/tool identity,
selected task group, sufficient scope alternatives/conjunctions, known data
limitations, provider evidence, and deterministic acceptance fixtures.

Effective permission requires all of:

- the task is selected in current Toolkit configuration;
- its sufficient scope set is proved for the current grant;
- current grant and application binding are eligible;
- the exact remote schema is supported and currently available;
- current Toolkit/Team execution authority admits the call.

Scope comparisons use exact normalized provider scopes and reviewed implication
rules. `readonly` substrings, `readOnlyHint`, successful redirects, and public
`tools/list` cannot establish scope authority.

Known examples are requirements tests, not a finalized mapping: Calendar readonly
must expose no write tools; Gmail denied must not disable independently permitted
Calendar work; restricted Drive access must not promise unrestricted whole-Drive
search. Gmail public discovery returned no send tool. Do not request `gmail.send`
or create an API wrapper merely to fill an unsupported MCP task.

### Schema Discovery

Reuse nonblocking background MCP discovery. A stable source key includes Toolkit
and service identity; exact remote-tool routing survives duplicate names across
services. Existing final namespace reservation and deterministic sorting remain.
Snapshots contain schemas only. Join current authorization before model projection
and re-filter after configuration/grant changes even if discovery has not refreshed.

Unknown tools or unsupported schema contracts remain absent. A failed refresh can
retain a previous successful schema but cannot restore permission. No synchronous
discovery per model turn, loading pseudo-tool, or retry pseudo-tool is introduced.
Schema removals/changes that cannot be validated fail closed for affected tools.

### Execution Boundary

Reload current exact Toolkit eligibility, selected tasks, grant evidence/client
binding, and Team owner fence. Reject stale captured authority before outbound I/O.
Resolve the fixed service endpoint and token only after admission, and perform
MCP I/O outside database transactions.

No DB transaction spans Google execution. Once an admitted request is in flight,
local permission changes cannot promise reversal of a completed remote effect.
Subsequent calls and post-I/O persistence revalidate current authority.

Resource ACLs and organization policies remain distinct from scope grants. A
resource-specific 403 cannot prove global revocation. Definitive missing-scope
evidence makes affected tasks unavailable; uncertain failures cannot silently
promote previously unknown capabilities.

## Refresh and Concurrency

The mandatory common contract, independent of D1–D3, is:

1. Load detached current credential/client/permission evidence in a completed read.
2. Perform refresh through supported SDK APIs outside any DB transaction.
3. Finalize under the exact Toolkit/grant lock order and compare loaded credential
   state, subject/client binding, selection where relevant, and current authority.
4. A concurrently committed replacement, disconnect, configuration change, or
   winning refresh prevents the stale result from updating credentials or status.
5. Refresh success adopts verified returned scope changes. Legitimate omission
   retains only same-grant evidence justified by tested provider semantics.
6. Definitive `invalid_grant` or binding rejection marks only the still-matching
   grant unusable. Transient failures preserve durable authorization.

Locks are not held over provider I/O. Correctness does not depend on singleflight,
Redis, invalidation events, or a refresh task's process lifetime.

On a proved authentication rejection, at most one safe refresh/retry can be used
when the provider proves the first operation had no effect. Ambiguous transport
failure or unknown write outcome is not automatically retried. Reconnect never
replays the Agent's earlier task.

### Required Race Outcomes

| Interleaving | Required common result |
| --- | --- |
| Cancel/expiry versus callback result | Late candidate finalization rejected |
| Manager authority removed during exchange | No verified result publication |
| Two confirms | One Toolkit/outcome |
| Disconnect versus refresh | Deleted grant not resurrected |
| Refresh versus newer grant replacement | Older result discarded |
| Old cached tool versus lost permission | Projection and call both deny |
| Operator binding changes during I/O | Mismatched result cannot commit |

**Pending D3** selects whether the old saved grant continues running during an
ordinary reconnect, and how a reviewed reduced/account-changed result replaces
it. Staged replacement is the recommendation in the ADR, not approved behavior.
Both admitted options must retain the race outcomes above.

## Management Interfaces and Frontend

Route file names are local details. Contracts follow current ownership-specific
public Toolkit routing; exact-Agent and shared requests never use a looser common
ownership test.

| Operation | Input boundary | Result/effect |
| --- | --- | --- |
| Preparation | Exact setup context | Redacted operator readiness, missing prerequisite and responsible role |
| Start | Desired service/task selection | Persisted unpublished attempt and SDK authorization URL |
| Exchange | Code/state for exact authenticated attempt | Redacted verified/unknown/failure result; no Toolkit |
| Review/read result | Exact attempt and current authority | Actual identities/capabilities and next actions |
| Confirm | Exact reviewed result and final nonsecret settings | Atomic initial publication and inspectable outcome |
| Cancel | Exact unpublished attempt | Idempotent local abandonment; no provider revocation |
| Saved reconnect | Exact managed Toolkit | Ordinary reconnect; replacement contract pending D3 |
| Disconnect/delete | Exact managed Toolkit | Existing local management boundary; no promised reversal |

Tokens, secret values, PKCE, plaintext state, internal effective generations, and
raw provider data never enter public projections. Revalidate input rather than
trusting browser capability booleans. New routes/types require generated OpenAPI
and Python/TypeScript client regeneration during implementation.

The setup container owns a discriminated state union; views remain pure. Use
existing progressive setup/actual scroll-container conventions. Earlier selections
stay reviewable, focus changes only on explicit progression, mobile has no
horizontal overflow, controls remain keyboard usable, and reduced motion is
respected. Resume state is nonsecret and not authoritative.

The UI distinguishes missing operator preparation, authorizing, verification
pending, full/partial/zero/unknown grants, failed verification, confirm pending/
unknown, and reconnect-required. It explains task-level work in localized copy
instead of presenting raw scope codes as the main explanation.

**Pending D1/D2/D3:** operator entry/input projection, identity cardinality, and
saved reconnect continuity. These unresolved screens are not filled with invented
defaults or additional-consent controls.

## Security and Operations

- Existing manager, exact Agent, Workspace membership, System Admin, and Team owner
  boundaries remain authoritative. No account identity comes from a chat sender.
- Use SDK-owned OAuth and identity verification; no hand-written token signature
  verification or arbitrary provider HTTP implementation.
- Encrypted secrets are not diagnostic data. Log stable operation IDs, phase,
  service, normalized reason, and safe provider status; never contents, subject
  email, tokens, credential fingerprints, or credential-bearing URLs.
- Existing logger integration owns error reporting. Unexpected invariants remain
  observable failures; cancellation remains cancellation.
- Missing configuration affects only this optional integration. Local validation,
  operator readiness declarations, public endpoint availability, actual account
  grant, and successful tool behavior are different evidence.
- Network timeouts retain current MCP controls. No unbounded retry, background
  consent, write replay, or remote revocation cleanup is introduced.

**Pending D4:** prompt/response scanning enforcement and accepted-risk disclosure.
Google's published guidance requires an actual screening approach. A warning or
ordinary untrusted-content prompt alone is not a verified substitute. Until D4
and its evidence close, this design cannot claim live/provider-policy readiness.
Model Armor must not be enabled by this documentation PR.

## Migration, Rollout, and Recovery

- Google is a new provider. No existing generic MCP OAuth row is converted or
  reinterpreted as verified Google scopes. Existing integrations retain their
  current single-server authentication semantics.
- Add only state necessary for the chosen Google lifecycle. Generate Alembic
  migration and revision references during implementation; maintain one linear
  migration head. Backfill unrelated credentials is out of scope.
- Google-specific token decoding retains scope/identity evidence before any SDK
  normalization loses absence information. Shared token model additions, if
  needed, preserve existing provider defaults and wire behavior.
- Deliver schema support before emitting saved Google Toolkit types; verify old
  application behavior with an unknown type before any rollback claim. Do not
  invent a compatibility shim or destructive downgrade.
- Rollback can stop exposure of Google execution while preserving encrypted
  persisted data. Data deletion or external revocation is a different authority.
  The concrete safe deployment/rollback sequence needs mixed-version tests.
- Setting/binding effects follow D1; saved replacement follows D3. They are not
  selectable rollout modes or unapproved historical-secret fallback.

Expected implementation decomposition after approval is provider/lifecycle and
fixtures, management API and generated clients, frontend/reconnect, then Living
Spec synchronization and same-SHA QA. This is a delivery outline, not an
implementation plan or permission to start code.

## Test Strategy

### E2E Primary Matrix

Required backend E2E uses real public APIs, repository state, and ownership routes
against deterministic OAuth/MCP fixtures. Web E2E uses the real setup/navigation/
return/review/publish flow. Live Google access is not a required CI dependency.

| Scenario | Primary evidence |
| --- | --- |
| Unconfigured operator | Correct responsible role, no consent start or secret leak |
| Full consent | Verified identity and selected tasks; nothing executable before confirm |
| Partial/empty grant | Calendar readonly filters writes; denied Gmail does not fail Calendar; zero is not usable |
| Missing/malformed grant evidence | Unknown/invalid rather than guessed full consent |
| State, issuer, audience, nonce, Session, ownership mismatch | No exchange/publication from wrong authority |
| Cancel, reset, expiry, late callback | No executable candidate; no unrelated revocation |
| Confirm replay/race/lost response | Exactly one durable publication and truthful result lookup |
| Grant narrowing after cached discovery | Both model projection and actual execution reject stale tools |
| Unknown/changed schemas and duplicate service tool names | Fail-closed policy and exact endpoint routing |
| Refresh race, rotation, omission, invalid_grant | Same-grant evidence only; stale result cannot overwrite |
| ACL/policy/transient/uncertain-write failures | Correct localized state; no fabricated global revocation or write replay |
| Ordinary reconnect | D3 outcome and fresh grant review; no per-task consent or in-run OAuth |
| Team/shared and Agent-only | Existing management/execution fences and account-sharing warning |
| Existing MCP/Notion/Sentry/GitHub/GCP | Unchanged current provider contracts |
| Keyboard, focus, mobile, reduced motion | Browser behavior plus focused component/Storybook verification |

D1–D4 add their exact acceptance rows when selected. In particular, client
replacement/secret rotation, account projection, reconnect continuity, scanner
outage/coverage and disclosure tests cannot be asserted from unaccepted proposals.

### Fixture and Prerequisite Support

Use established testenv provider fixtures because required tests need deterministic
partial consent, provider failures, and controlled races without secrets.
Seed an operator, authorized manager, unauthorized member, two Workspaces/Agents,
two clients and subjects, selected task sets, full/partial/empty/missing grants,
scope-loss refresh, callback denial, refresh rotation, and controlled same-name
MCP tools. Explicit barriers establish race ordering; do not use sleeps.

Testenv is prerequisite/diagnostic support, not a substitute for product E2E.
Unit tests own scope-policy truth tables and typed provider decoding. Component
tests own copy/state rendering; neither alone proves actual authorization.

### Live Verification and Evidence

Live work requires an approved isolated Google project, Preview eligibility,
configured APIs/MCP services, registered deployment callback, client and consented
test account. Record a redacted prerequisite snapshot and exact SHA, selected
tasks, actual returned grant evidence, endpoint/tool mapping, renewal outcomes,
and limitations. Never publish raw secret/token/account content.

Start with metadata/identity/read-only verification. Writes need explicit approval
and isolated resources. Gmail sending is not inferred from ordinary API scopes.
Live prerequisites absent: explicit skip and conditional feasibility.
Prerequisites present but a scenario fails: record failure, not a silent skip.

CI must run required deterministic authorization/publication/race E2E and Web
flows, applicable unit/component tests, generated-client synchronization, and
documentation checks at the same SHA. Optional live results are reported separately.
Public discovery or fixture success cannot be called authenticated interoperability.

## Design Authority

- Design revision: `1`.
- The following stable IDs cover only independently authorized common mechanisms.
  Recommendations D1–D4 are outside this set. Their acceptance creates new IDs and
  a new revision; it cannot retroactively authorize this draft.

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Bounded Google provider and fixed official service routing, existing MCP facilities | REQ-1, fixed official-MCP/compatibility constraints; retained Toolkit provider composition | derived |
| M2 | Selected task policy intersected with proved grants; unknown tools fail closed | REQ-3, REQ-5 | required |
| M3 | Unpublished authorization and explicit review before initial atomic publication | REQ-4, REQ-6; retained Toolkit namespace/ownership obligations | derived |
| M4 | Exact initiator/context callback and post-I/O current-authority validation | REQ-4, REQ-8; retained exact ownership boundaries | derived |
| M5 | Requested/granted/unknown evidence and verified principal separation | REQ-4, REQ-5, REQ-6 | required |
| M6 | Existing Agent/shared management, Team execution and remote Runtime-free scope | REQ-8; retained Toolkit contracts | existing |
| M7 | Per-service background schema projection plus current execution recheck | REQ-5, REQ-7; retained nonblocking MCP discovery and Team fencing | derived |
| M8 | Detached refresh and exact stale-result comparison; no grant resurrection | REQ-5, REQ-7; retained MCP refresh transaction boundary | derived |
| M9 | Ordinary reconnect only; no consent/replay initiated by Agent execution | REQ-7 and non-goals | required |
| M10 | Encrypted/redacted credential boundaries and local-only abandonment | REQ-4, REQ-7, REQ-8; retained credential cipher and disconnect contract | derived |
| M11 | Progressive accessible same-context setup and truthful per-task feedback | REQ-1, REQ-4, REQ-5, REQ-9 | required |
| M12 | Preserve unrelated providers and their durable credential authority | Fixed compatibility/data-preservation constraints; retained MCP and Toolkit Specs | existing |

Physical table names, SDK adapter/helper names, equivalent typed model layout,
fixture names, timeout constants within current contracts, and route file layout
are agent-owned. They cannot change storage authority, account cardinality,
secret-retention policy, recovery semantics, or configuration modes.

### Bidirectional Coverage

| Requirement | Common mechanism IDs | Pending choice or feasibility dependency |
| --- | --- | --- |
| REQ-1 | M1, M6, M11 | D2 identity cardinality |
| REQ-2 | M1, M4, M10 | D1 operator registration; Preview/configuration evidence |
| REQ-3 | M2, M5 | Proved supported task/scope catalog |
| REQ-4 | M3, M4, M5, M10, M11 | D1 binding and D2 identity projection |
| REQ-5 | M2, M5, M7, M8 | Actual scope-to-tool and refresh semantics |
| REQ-6 | M3, M5, M6, M11 | D2 review identities; D3 saved replacement |
| REQ-7 | M7, M8, M9, M10 | D3 reconnect continuity |
| REQ-8 | M4, M6, M10, M12 | D4 screening/disclosure; D2 account relationship |
| REQ-9 | M11 | Browser/layout verification |

The common authority audit passes by construction; the whole Design authority
audit is incomplete because pending mechanisms have not been accepted or added.
Coverage of a requirement is not a claim that its dependencies are closed.

## Feasibility Validation

| Boundary | Classification | Evidence and closure |
| --- | --- | --- |
| Provider composition and shared transport | feasible | Existing GitHub/GCP compose MCP; fixed URLs need no generic config migration |
| Candidate/publication and exact authorization | feasible | Existing GitHub creation and ownership-specific repository operations; Google implementation/tests still needed |
| Operator registration resolution | conditional | Typed System Settings exists; D1 and operator entry context unresolved |
| Requested versus actual grant evidence | conditional | Token model currently omits scope; Google SDK decoding/identity and omission behavior require fixtures and live verification |
| Scope-to-tool policy and endpoint grant reuse | conditional | Public discovery 9/8/23 tools, no scope authority in inspected schemas; live mapping and D2 needed |
| Refresh and stale-result protection | feasible common contract; conditional provider behavior | Existing detached CAS refresh; Google offline/rotation/omission behavior unverified |
| Saved reconnect | conditional | Common fences specified; D3 required for continuity/replacement contract |
| Provider security compliance | blocked for live readiness | D4 has no selected/verified scanner and risk-disclosure solution |
| Additive migration and rollback | conditional | Existing rows remain untouched; unknown-type mixed-version behavior must be tested |
| UI/accessibility and required verification | feasible plan | Existing progressive setup, public E2E fixture and Web lanes; new scenario coverage not yet executed |

Unauthenticated metadata and `tools/list` establish reachability/catalogs only.
No real account/token, user-data call, renewal, or write was used. No blocker is
waived by a common architecture recommendation. Conditional provider claims must
close before final readiness, and unapproved material alternatives require ADR
selection before a complete Design approval candidate can be produced.

## Removal and Replacement

| Existing unit/behavior | Removal authority | Replacement or remaining authority | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Existing generic MCP config/OAuth state | None; preserve | M12 and current Specs | No migration/reinterpretation | Regression E2E and migration fixture comparison |
| Existing GitHub/GCP/Analytics and other provider paths | None; preserve | M1, M12 | New Google provider only | Existing provider E2E and effective Toolkit resolution |
| Existing ungranted schema exposure for other providers | None; preserve | Current contracts | Google filtering is scoped | Provider-specific tests; no generic policy change |
| New Google prototypes/temporary bypasses, if introduced during implementation | Only behavior-preserving consolidation into M1–M12/accepted later mechanisms | One approved Google lifecycle | Implementation cleanup; no second authority | Call-site/config/schema search plus primary E2E |
| Hand-edited generated client artifacts | Prohibited by project generation rules | Generated OpenAPI clients | Regenerate during API implementation | Generation produces no unexplained diff |
| Stale confirmation wording in supporting draft | Confirmed scope, documentation process | Requirements and primary ADR/Design | This documentation change only | Snapshot links/catalog and no second approval authority |

No current production Google-specific implementation/state was found to remove.
No existing authoritative contract, credential, table, fixture, or configuration
is scheduled for deletion by this draft. Accepted D1–D4 may create new retirement
obligations, which must be added with their exact authority.

## Design Approval

- Mode: `Collaborative`.
- Decision owner: requester.
- Approved on: not approved.
- Approved Design revision: none.
- Approved authority IDs: none.
- Proposed common scope: M1–M12, plus D1–D4 mechanisms only after acceptance and
  a revised bidirectional authority/feasibility audit.

The instruction to continue technical design confirms the scope and permits
drafting. It is not approval of pending alternatives, provider-policy exceptions,
implementation, deployment, or this complete Design revision.
