---
title: "Agent-Scoped Model Inference Backend Requirements"
created: 2026-10-28
updated: 2026-10-29
tags: [engine, inference, security, backend]
document_role: primary
document_type: requirements
snapshot_id: relay-261028
---

# Agent-Scoped Model Inference Backend Requirements

- Snapshot: `relay-261028`
- Document reference: `relay-261028/REQ`

## Problem

The Azents harness currently invokes models through the Worker execution path.
A separately callable, Agent-authorized inference backend is needed before that
call site can be replaced and before the harness can move into Runtime. A
caller outside the trusted server boundary must not gain access to another
Agent's models or provider accounts merely by changing request fields.

## Primary System Outcome

An independently deployable inference backend can be exercised using
system-issued Agent credentials and the Agent's existing model configuration,
while the current Worker inference path remains unchanged.

## Supporting Scenarios or Effects

- Different Agents and Workspaces use the same public model name with different
  authorized provider accounts.
- A caller selects a specific configured target, changes models between calls,
  and retains control of retry and candidate fallback.
- Development verification exercises the real authentication and inference
  boundary without adding user-facing credential management.
- System token replacement does not disrupt already admitted inference.

## Goals

- Establish an authenticated, independently testable backend for the Azents harness.
- Preserve required inference capabilities and expose unsupported behavior honestly.
- Bound the authority of leaked Agent credentials.
- Reuse the existing model configuration, integration ownership, and provider
  credential lifecycle rather than create competing sources of truth.

## Non-Goals

- Replacing the Worker loop's call site or moving the harness into Runtime now.
- A second Azents canonical inference protocol or an independently managed model map.
- User-managed Agent API keys or a new settings UI.
- Proxy-owned candidate selection, general retry, or cross-account fallback.
- Durable inference jobs, result recovery after reconnect, or transfer of an
  in-flight inference stream between replicas.
- Revocation-driven cancellation of already admitted calls.
- Custom distributed rate limiters, budget reservation systems, or a separate
  Azents Proxy usage ledger and delivery queue.
- Extended target discovery in the model listing.

## Requirements

### REQ-1. Independent backend verification

The backend must be testable independently of the existing execution loop.

**Acceptance criteria**

- A privileged development flow issues a scoped credential and invokes the real
  backend without rerouting current Worker traffic.
- Disabling the new backend leaves the existing Worker inference path intact.
- Completion evidence distinguishes the new backend from the later Worker and
  Runtime migrations.

### REQ-2. Existing settings remain authoritative

Calls must use targets derived from the authenticated Agent's existing model
configuration and Workspace-owned integrations.

**Acceptance criteria**

- No separate Proxy model/account mapping is required or maintained.
- Every configured candidate can be addressed individually; a label's list is
  not silently reduced to its first candidate.
- The same public model name may resolve to different accounts for different
  authenticated Agents, including Agents in one Workspace.
- Distinct accounts for the same model can be selected unambiguously within an
  Agent's allowed configuration.
- Candidate reordering does not redirect an existing target to a different account.
- A target identifier alone grants no authority. New calls validate current
  membership in the Agent's configuration and current integration availability.
- Listing models is optional discovery and is not proof of invocation permission.
- An admitted call retains its selected model/account; later calls see settings changes.

### REQ-3. External callers cannot expand authority

Agent inference credentials must remain narrowly scoped even if disclosed.

**Acceptance criteria**

- Changing Agent, Workspace, model, target, credential, routing, endpoint, or
  authentication-header inputs cannot obtain an unauthorized model or account.
- Denied requests do not dispatch provider inference.
- No default account or cross-Workspace route is used when authorization or
  credential resolution fails.
- Agent credentials cannot access management functions, obtain provider secrets,
  or mint replacement credentials.
- Model discovery reveals only allowed public models.
- Failure responses do not disclose other Agents' configuration or secret material.

### REQ-4. System-managed inference credentials

Agent inference credentials are issued and supplied by the system, not managed
as end-user API keys.

**Acceptance criteria**

- Issuance and delivery require a trusted system path; developer verification is
  available through system Admin/Internal access, not Workspace role alone.
- Rights belong to the Agent; issuance, rotation, and revocation are separated by
  supply target so development-token revocation does not revoke operational tokens.
- Tokens are valid for one hour. Routine replacement starts five minutes before
  expiry; overlap ends within five minutes and never extends the old token's expiry.
- A failed replacement delivery does not extend the old token's lifetime.
- Expiry and revocation reject new admissions without cancelling already admitted calls.
- The inference credential cannot indefinitely renew itself.
- Stored verification material cannot be used to retrieve the original issued token.
- Operational automatic delivery into Worker and Runtime is subsequent work;
  this stage verifies the lifecycle through privileged development access.

### REQ-5. Preserve provider credential custody

Azents remains responsible for provider credentials and OAuth refresh.

**Acceptance criteria**

- Agent execution clients do not receive upstream provider secrets.
- A new call requires both an authorized Proxy identity and a valid Agent identity
  before any provider credential is supplied.
- The Proxy's service credential alone cannot read arbitrary integrations or
  issue Agent inference credentials.
- Only credential material necessary for the authorized call is supplied;
  subscription refresh tokens remain with Azents.
- Model discovery neither releases provider secrets nor refreshes OAuth tokens.
- Concurrent credential refresh cannot overwrite newer reauthentication state
  with superseded results.

### REQ-6. Required inference fidelity

The backend must expose the inference capabilities needed by the Azents harness,
with provider-specific support and unsupported cases made explicit.

**Acceptance criteria**

- Verify text and streaming output, structured output, client tool calls/results,
  and applicable reasoning/native continuation information.
- Verify ChatGPT and Grok subscription routes separately from ordinary API-key routes.
- Verify supported provider-hosted web search and image generation, including
  activity/output and source or file content needed for subsequent calls.
- Verify model changes between calls, including cross-provider tool and image
  history, rather than only acceptance of a different model field.
- Verify prompt-cache controls and observed cached-token details; requesting a
  cache does not constitute evidence of a real cache hit.
- Preserve supported Fast/Priority behavior without silently treating lower
  reasoning effort as the same feature.
- Unsupported routes or capabilities must not be presented as verified support.
- No new per-Agent premium-option policy is introduced by this requirement.

### REQ-7. Caller-owned attempts and connection-bound execution

The caller retains model-target selection, same-target retry, and candidate fallback.

**Acceptance criteria**

- The backend does not automatically replace the selected target or generally
  replay a failed inference request.
- SDK/transport recovery is examined separately from logical retry settings;
  verification records actual upstream dispatches at failure boundaries.
- Client disconnect and ordinary timeout follow bounded cleanup behavior.
- Incomplete or disconnected calls are not reported as completed success.
- Token expiry/revocation or settings changes do not themselves cancel admitted calls.
- Provider-side work or cost is not claimed to be undone by cancellation.

### REQ-8. Usage and privacy-preserving observability

Return observed usage and provide useful operational diagnostics without storing
inference content or credentials in operational logs.

**Acceptance criteria**

- Preserve available input/output, cache read/write, reasoning, modality, and
  provider-reported tier/cost details without double-counting subset fields.
- Separate observed usage, missing information, estimates, and actual billing;
  subscription token counts are not represented as API invoices.
- Attribute operational records to server-verified Agent, Workspace, and actual
  integration identities rather than client-supplied identity metadata.
- Operational logs omit prompts, responses, tool arguments/results, media bytes,
  auth tokens, secret headers/settings, and unsafe raw provider errors.
- Retain safe request correlation, outcome, latency, usage, and failure classification.
- Use built-in Proxy observability; do not add an Azents usage ledger or retry queue.

### REQ-9. Bounded operational footprint

The deployment must remain small without imposing artificial scaling restrictions.

**Acceptance criteria**

- Start independently with one replica as a deployment value, not a code or chart
  restriction against larger replica counts.
- Authorization does not depend on sticky routing or a Pod-local authority store.
- Use only suitable built-in limits; do not build new distributed limit/budget systems.
- Do not describe per-process counters as service-wide limits without shared coordination.
- Make Pod-failure and shutdown limitations explicit; another replica does not
  imply resumption of a failed stream.

### REQ-10. Evidence-based readiness

Readiness must be demonstrated with bounded deterministic tests and clearly
separated authorized live-provider evidence.

**Acceptance criteria**

- Exercise real backend ingress, scoped issuance, internal authorization, model
  configuration resolution, and provider dispatch using controlled fixtures.
- Test same-model/different-account routing, forbidden overrides, expiry,
  revocation, rotation overlap, and current-settings revalidation.
- Use focused lower-level tests for provider permutations and only representative
  end-to-end flows for the assembled boundary.
- Run only authorized live-account checks; report unavailable checks as unverified,
  not as passing because mocks succeeded.
- Demonstrate required Proxy extension paths without Enterprise code or entitlement.

## Fixed Constraints

- Use the actual LiteLLM Proxy and its unified inference contract as the backend,
  not a self-built server merely embedding the LiteLLM library.
- Keep the initial Agent-facing surface limited to Responses invocation and
  standard, permission-filtered model discovery. Do not add target-list fields.
- Start in a separate Pod; final placement during harness relocation remains deferred.
- Use the MIT-covered LiteLLM feature surface and independently authored Azents
  integration code; do not bypass Enterprise license checks.
- Use officially published dependency releases. Unreleased development commits
  must not be selected as runtime dependencies; prefer the published distribution
  wheel rather than building an unreleased upstream checkout. The requester
  approved one exception on 2026-10-29: use the officially published LiteLLM
  development release carrying request-local ChatGPT credential forwarding,
  then replace it with a stable release containing that fix. Record the reason
  and stable-transition condition beside the dependency pin. This does not
  authorize arbitrary prereleases, a source build or a maintained vendor patch.
- Protect Proxy-to-Azents calls with dedicated service authentication, TLS, and
  private network access. Issuer privileges remain separate from resolver privileges.
- This snapshot is design work; implementation, deployment, and live account use
  require their applicable execution authorization.

## Open Assumptions

- Live subscription availability and hosted-tool entitlement depend on the selected
  accounts and models; no universal subscription entitlement is assumed.
- Existing model configuration is the authority for allowed targets. Detailed
  treatment of client-selectable sampling/tool settings must be checked against
  existing semantics without inventing a new settings authority.
- Exact built-in rate-limit values are deployment settings, not new product controls.

## Confirmation

The requester confirmed this complete consolidated snapshot on 2026-10-28
before formal ADR and Design creation. The preceding discussion supplied the
individual scope and technical choices. This confirmation authorizes design work,
not implementation, deployment, or final Design approval.

On 2026-10-29, the requester explicitly required officially released packages
after the implementation had selected an unreleased LiteLLM commit. This fixes
the dependency-delivery constraint; it does not approve a vendor patch, reduced
provider scope, merge, deployment or live-account use.

Later on 2026-10-29, the requester approved the single published-development-release
exception above and directed completion of all remaining approved implementation
and specification work. Merge, deployment and live-account use remain separate.
