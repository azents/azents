---
title: "GitHub Toolkit Connection Wizard Technical Decisions"
created: 2026-10-13
document_role: primary
document_type: adr
snapshot_id: github-261013
tags: [github, toolkit, frontend, security, architecture]
---

# GitHub Toolkit Connection Wizard Technical Decisions

- Snapshot: `github-261013`
- Requirements: [github-261013/REQ](../requirements/github-261013-connection-wizard.md), requester-confirmed on 2026-10-13.
- Mode: Collaborative.
- Decision owner: requester.
- Accepted decisions: `github-261013/ADR-D1`, `github-261013/ADR-D2`, `github-261013/ADR-D3`.

## Fixed and Derived Outcomes

- Retain the five authentication modes and existing exact ownership/management boundaries (REQ-2, REQ-9).
- Keep user-account candidates encrypted and unpublished, with Toolkit, connection, and Agent namespace published atomically at final confirmation (REQ-7, REQ-9; existing [Toolkit Spec](../spec/domain/toolkit.md), GitHub User Account Authority).
- Apply the settings actually reviewed after authorization (REQ-5, REQ-6, REQ-7).
- Retain Runtime OFF default, explicit risk acknowledgment, non-expiring user-token requirement, exact cancellation, bounded fail-open cleanup, and current Worker resolution.
- Allow pre-publication close/reset; temporarily restrict them only while the final publication outcome is pending (REQ-8).
- Limit replacement to new GitHub creation. Keep saved-Toolkit editing, other Toolkit types, and existing credential execution authority (REQ-1, REQ-9).
- Automatic App creation, new durable draft behavior, token refresh, credential fallback, and product versioning are excluded.

## Material Decision Map

Accepted entries cite their recorded decision. Pending entries are not implementation authority.

| Topic | State | Owner | Consequence |
| --- | --- | --- | --- |
| Final post-authorization settings publication boundary | Accepted: ADR-D1 | Requester | Final settings in the atomic confirmation command; no separate attempt-settings update |
| Verified GitHub setup identity projection contract | Accepted: ADR-D2 | Requester | GitHub-scoped setup verification; preserve the provider-neutral connection-test contract |
| Platform App label source and freshness | Accepted: ADR-D3 | Requester | On-demand SDK lookup; no new retained display-name authority or refresh actor |

State identifiers, component filenames, equivalent local structures, helper boundaries, and fixture composition are Agent-owned details. They may not add state authorities, contracts, user-visible behavior, or operational modes.

## ADR-D1. Final Settings in the Atomic Confirmation Command

- Accepted on: 2026-10-13.
- Decision owner: requester.
- Authority: `github-261013/REQ-5`, `REQ-6`, `REQ-7`, and `REQ-9`.
- Choice: Option A.

### Decision

User-account creation confirmation receives the final allowlisted non-authentication settings together with the exact attempt ID. The server validates those settings and publishes Toolkit, current account connection, and applicable Agent namespace atomically, retaining the existing candidate and exact authentication/ownership binding. No separate operation updates settings in the unpublished attempt. Existing attempt storage, one-use semantics, expiry, and authority revalidation remain.

Authentication mode, App/source, ownership, credentials, and callback binding are excluded from the final-settings input. Validation errors preserve a still-live unpublished candidate for correction. Post-authorization edits do not become a durable server draft; reload recovery does not guarantee retention of those unsaved edits. All callers and generated clients must adopt the new confirmation contract; an attempt-ID-only fallback is not part of this decision.

### Requirement and Current Evidence

REQ-5, REQ-6, and REQ-7 require feature groups, Runtime injection, connection name, and other supported setup settings chosen after authorization to agree with the final saved result. The current creation service prepares a complete `ToolkitCreate` at connect. The creation repository retains that desired object in the encrypted attempt. Confirmation takes an attempt ID and creates from the retained desired object; it does not accept final settings.

Evidence at `bedfbfb2a14877fc84bda026ad71a02b1c3e5d87`:

- `python/apps/azents/src/azents/services/toolkit/__init__.py:prepare_user_creation`
- `python/apps/azents/src/azents/core/github_user_creation.py:GitHubUserCreationAttempt`
- `python/apps/azents/src/azents/services/github_user_oauth/creation.py:confirm`
- `python/apps/azents/src/azents/repos/github_user_oauth/creation.py:confirm`
- `python/apps/azents/src/azents/api/public/toolkit/v1/github_user_creation.py`
- `typescript/apps/azents-web/src/shared/toolkits/containers/useGitHubUserCreationContainer.ts`

The repository already locks the exact attempt, repeats live scope/App validation, and creates Toolkit, connection, and Agent namespace in one database-only transaction. The existing creation remains one-use; no repeated-create or uncertain-result replay guarantee is introduced here.

### Option A: Final Settings in the Atomic Confirmation Command

Add a strict, bounded non-authentication settings input to the user-account creation confirmation command. The user-authorized candidate and App/source/owner/registration/callback binding remain in the existing encrypted attempt. Validate the final settings under the normal Toolkit configuration and identifier rules, then combine only the permitted values with the exact locked candidate and publish once.

Final settings cover the existing supported setup metadata and execution settings, not credentials or ownership. The complete field allowlist and validation are Design work after this decision. The mechanism must use typed inputs, forbid extra fields, and preserve the exact authentication mode and authority binding; it cannot accept a generic replacement `ToolkitCreate`.

Advantages:

- No additional mutable server-side settings authority between review and confirmation.
- No preliminary settings-update write or additional update/confirm ordering.
- Final reviewed settings are the explicit input to the same atomic publication.
- Existing attempt storage and expiry can remain; no new durable setup model is required by this option.

Costs and risks:

- Changes the confirmation request contract and generated clients/callers.
- Validation failure must preserve the unpublished candidate so settings can be corrected while the attempt remains live.
- The final transaction must independently check the live attempt and authority; a prior service read is insufficient.
- Local post-authentication edits are not durable drafts. The existing server review may restore pre-edit defaults after reload; durable edit recovery is not authorized by this snapshot.

### Option B: Update the Unpublished Attempt, Then Confirm It

Add an exact-attempt operation that changes only permitted non-authentication settings in the encrypted unpublished attempt. After that operation succeeds, confirmation publishes the stored settings using the existing attempt-ID-only shape.

Advantages:

- The server can return the retained final settings for review/resume before publication.
- Keeps the confirm command centered on the already-reviewed stored object.

Costs and risks:

- Introduces an additional writable setup-settings contract and database operation.
- Must define update/confirm/cancel/expiry serialization and ensure the confirming client publishes the settings it reviewed rather than another interleaved update.
- Server retention of post-authentication settings adds a freshness/ownership obligation not required for the approved non-durable draft scope.
- Keeping the confirm shape does not eliminate client/server contract work for the added update operation.

### Recommendation and Excluded Approaches

Option A was selected because the requirement is correct final publication, not an autosaved server draft. It reuses the existing one-use candidate and publication boundary without adding another mutable setup-settings operation. Option B was rejected because its additional mutable settings contract and update/confirm ordering are unnecessary for the approved scope.

Creating the Toolkit first and updating it afterward is excluded because it permits partial publication and violates REQ-7. Reauthorizing on every toolset, Runtime, or name edit contradicts the approved post-authentication continuation and is not a viable solution to this requirement.

### Acceptance State

The requester accepted Option A on 2026-10-13 after the options, trade-offs, and recommendation were presented. This is the first accepted material technical decision. The verified identity projection contract and Platform App metadata source remain unresolved; no primary Design is finalized.

## ADR-D2. GitHub-Scoped Setup Verification

- Accepted on: 2026-10-13.
- Decision owner: requester.
- Authority: `github-261013/REQ-3`, `REQ-4`, and `REQ-9`.
- Choice: GitHub-specific verification API rather than expanding the provider-neutral connection-test response.

### Context

The existing generic unsaved connection-test route delegates to `GitHubToolkitProvider.test_connection`. Its `TestConnectionResult` describes MCP connectivity and discovery, not a verified GitHub account or App identity. Installation testing exchanges a token for the first selected installation; that is not proof of access to every selected target. The approved Wizard must display verified account/App information and distinguish App identity from installation owners.

### Decision

Introduce a management-authorized GitHub setup verification API that returns strict, allowlisted identity and applicable installation information, reusing existing exact-scope management admission and supported public asynchronous GitHub SDK operations. Preserve the generic MCP connection-test contract for other Toolkits and its existing consumers.

The projection must distinguish GitHub identity verification from MCP connectivity and target-specific access. It may reuse existing transport tests without claiming that their success verifies every repository. An existing OAuth user-account candidate remains the authority for that account; the new verification projection does not replace its exchange/review/confirmation lifecycle.

Verification does not publish a Toolkit, create a new credential store, persist a credential authority receipt, grant execution authority, or authorize a client-supplied account label. Tokens, App private keys, and OAuth secrets remain excluded from outputs and logs. Provider failures must not become successful or fabricated identity results.

### Alternatives and Consequences

- **Selected:** GitHub-scoped verification preserves provider-neutral MCP semantics, while adding an explicit GitHub public contract, generated clients, and deterministic identity/error fixtures.
- **Rejected:** Expanding the generic connection-test response would couple the common Toolkit verification contract to GitHub-specific account and installation metadata.

The complete request/response allowlist, shared/Agent route symmetry, and reuse boundaries are Design work under this decision. Platform App name retrieval and persistence are not decided here.

## ADR-D3. On-Demand Platform App Name Lookup

- Accepted on: 2026-10-13.
- Decision owner: requester.
- Authority: `github-261013/REQ-3`, `REQ-4`, `REQ-9`, and `ADR-D2`.
- Choice: Option A.

### Decision

Resolve the current Platform App registration at the setup operation boundary and fetch its authenticated metadata through the supported asynchronous GitHub SDK. Verify the returned numeric App ID and expose only allowlisted display metadata. A new setup load or explicit retry obtains current metadata; an open form is not a subscription to provider-side renames.

Do not add display-name persistence, a name configuration field, a refresh actor, a metadata versioning feature, or a retained-name fallback. Provider loading/error remains distinct from registration absence/incompleteness. Auth and publication use existing numeric identity and registration checks, not the displayed name.

### Current Evidence

- `PlatformGitHubAppRuntimeService.resolve` returns an operation-bound effective registration without process-local caching.
- Public setup availability currently exposes no App name.
- `PlatformGitHubAppValidationClient` obtains App metadata during registration validation but retains only `app_slug`, not the display `name`.
- Admin details expose retained `app_slug` only when the existing validated-generation binding matches the current effective registration.
- `core/github_auth.py:get_app_slug` already uses the public asynchronous GitHub SDK App operation. A typed projection can read `id`, `name`, and `slug` from the same provider boundary.

Current persisted validation metadata is not sufficient to guarantee the actual current display name. No new product versioning feature is authorized.

### Option A: On-Demand Name Lookup

During setup metadata loading, resolve the current effective Platform App and request its authenticated metadata through the supported SDK. Verify the returned App ID against the admitted numeric App identity and expose the allowlisted name/slug to the management UI. Each new load or explicit retry obtains current provider metadata; an open form is not a live subscription to name changes.

Do not persist the label in a new server metadata authority or configuration field. Keep metadata loading/error distinct from locally confirmed registration absence or incompleteness. A timeout or provider failure shows retry rather than silently removing the Platform option or substituting an example name. Authentication and publication continue to use their existing operation-bound registration checks; the display label is not authority.

This avoids label storage, refresh scheduling, and retained metadata freshness obligations. It adds bounded GitHub I/O to setup metadata loading and therefore delays the named option when GitHub is slow or unavailable. It does not introduce a polling service, retry worker, or new fallback source.

### Option B: Retain Verified Name with Registration Metadata

Extend existing registration validation metadata to retain the provider-confirmed display name and expose it only under the current registration binding. Setup can then read the name without a new provider request when valid metadata exists.

This reduces provider calls during setup, but a GitHub-side rename remains stale until registration revalidation. Existing/environment-resolved registrations without retained name metadata need an explicit revalidation policy. This option requires deciding retained-label freshness and missing-metadata behavior; neither silently treating a slug as a display name nor hardcoding an example satisfies the approved wording.

### Recommendation and Acceptance State

The requester accepted Option A on 2026-10-13. On-demand metadata uses the current App without new retained name state or a refresh actor. Option B was rejected because retained display-name freshness and missing-name recovery add obligations unnecessary for this setup flow. All three current material technical decisions are accepted; the complete primary Design still requires authority/feasibility validation and revision-bound approval.
