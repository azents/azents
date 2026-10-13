---
title: "Google Service Connection Requirements"
created: 2026-10-13
document_role: primary
document_type: requirements
snapshot_id: google-261013
tags: [google, toolkit, oauth, integration, frontend, security]
---

# Google Service Connection Requirements

- Snapshot: `google-261013`
- Document reference: `google-261013/REQ`
- Confirmation: pending requester confirmation of this repository snapshot.

## Problem

Self-hosting operators and authorized connection managers must currently combine
separate setup instructions, authentication settings, and service access checks to
let an Agent use Google data. Successful sign-in does not mean every requested
permission was granted or every service is usable. A technical-field-first form
makes setup, partial consent, and recovery difficult to understand.

## Primary Context

### Primary Actor

An authorized Toolkit manager creating a Google connection for a saved Agent.
The manager and hosting operator may be the same person.

### Primary Scenario

The manager chooses Google from the connection entry point, understands operator
prerequisites, selects needed services and tasks, authorizes an account, reviews
the capabilities actually available and the ownership context, and explicitly
confirms the connection. If the user grants fewer permissions than requested,
the manager can understand and review the reduced usable result.

## Supporting Scenarios or Effects

- A hosting operator configures an operator-owned Google authorization application
  using guidance appropriate to the current deployment.
- Workspace-shared creation retains its existing management and execution scope.
- Existing connection settings and ordinary reconnect remain the entry points
  for managing a saved connection.

## Goals

- Offer one understandable Google entry point for Calendar, Drive, and Gmail.
- Separate operator setup, account consent, actual capability, and publication.
- Respect partial consent without introducing a separate consent-request feature.
- Preserve existing Toolkit ownership and Team execution authority.

## Non-Goals

- Per-participant account switching or a new personal-account execution model.
- Google Cloud project creation or Preview enrollment performed by Azents.
- A mandatory managed integration SaaS or self-hosted third-party MCP relay.
- Service-account impersonation or domain-wide delegation.
- Automatic ingestion, realtime event subscriptions, or a new scheduling model.
- Credential injection into Runtime processes.
- A new generic approval workflow, provider fallback, or versioning feature.
- Per-capability additional-consent controls or a dedicated permission-management UI.
- In-run consent requests, a permission-request inbox, automatic OAuth navigation,
  or automatic replay of a task after authorization.

## Requirements

### REQ-1. Unified Google setup experience

Provide one Google entry point in which users choose Calendar, Drive, and Gmail
and understand each service's state without repeating unrelated setup flows.

**Acceptance criteria**

- Google is the primary connection entry, not three mandatory independent entries.
- Relevant setup sections appear progressively on one surface, with earlier
  choices available for review and correction.
- UI grouping does not promise one consent operation, shared account identity,
  or automatic access to every service.
- Saved Agent and Workspace-shared entry contexts retain their existing scope.

### REQ-2. Operator-owned preparation and guidance

Let a hosting operator prepare the integration using their own Google application,
and let a manager understand any missing prerequisites before account consent.

**Acceptance criteria**

- Guidance distinguishes Preview enrollment, product API/MCP service activation,
  authorization application setup, and deployment-specific callback registration.
- Internal and External account-audience restrictions are explained accurately;
  Internal is not described as an exemption from MCP Preview access requirements.
- An operator declaration of readiness is distinguished from a verified result.
- Missing prerequisites show the relevant next action and responsible role.
- Non-operators are not required to obtain or enter secrets they cannot manage.
- Integration remains optional for deployments that have not configured it.

### REQ-3. Purpose-specific service and task selection

Explain which work and data access each selection enables before requesting
Google consent. Request permissions relevant to the selected work.

**Acceptance criteria**

- Service choice and task choice distinguish meaningful capabilities such as
  Calendar reading versus editing and Gmail reading versus sending where supported.
- Unselected tasks do not trigger unnecessary permission requests.
- Restricted file access is not described as unrestricted whole-Drive search.
- Local task selection is not described as granting external account permission.
- Unconfirmed defaults and example tasks do not reduce the supported contract.

### REQ-4. Account consent and exact setup return

Explain requested permissions before consent and resume the same authorized setup
context after returning from Google.

**Acceptance criteria**

- The manager can distinguish the operator's authorization application from the
  Google account whose data the Agent will use.
- OAuth return alone does not mark all services usable or publish a new connection.
- Cancellation and provider denial offer recovery without fabricated success.
- Account or registration changes invalidate dependent verification evidence.
- Tokens, secrets, authorization codes, and plaintext callback state are not
  displayed in UI, prompts, screenshots, or ordinary diagnostic output.

### REQ-5. Actual consent and capability evidence

Handle users granting a subset of requested permissions, including partial access
within one service, and expose only capabilities currently permitted and selected.

**Acceptance criteria**

- Requested permissions and actually granted permissions are distinguished.
- A Calendar-read-only grant does not enable Calendar write tools.
- Denying Gmail permissions does not mark unrelated granted services as failed.
- Full grant, partial grant, no usable capability, pending verification, and
  verification failure have distinguishable feedback and next actions.
- Missing or ambiguous evidence is not presented as user denial or authorization.
- An unknown or unpermitted remote capability is not offered for execution merely
  because it was returned by remote tool discovery or previously cached.

### REQ-6. Explicit review and reduced-capability completion

Before a new connection becomes usable, require an explicit final review of the
actual identity, provided capabilities, unavailable work, and ownership context.
Permit review and completion of the confirmed reduced capability set.

**Acceptance criteria**

- Final review shows the actual account evidence and Agent-only or shared context.
- Work not granted is excluded from the published executable result.
- A subset grant can be completed after explicit review rather than forcing the
  user to grant every originally requested permission.
- No usable capability is not presented as a usable completed connection.
- Publication uncertainty is not reported as a proven cancellation or success.

### REQ-7. Setup recovery and ordinary reconnection

Handle setup cancellation, failures, and partial consent within the Google
connection flow. Use ordinary connection settings and reconnect for later
authorization changes rather than a new task-specific consent workflow.

**Acceptance criteria**

- Partial consent does not automatically start another authorization attempt
  or require a per-capability additional-consent button.
- Managers can use ordinary reconnect in connection settings when they choose
  to authorize again; the actual returned grants are checked again.
- Agent execution does not initiate a consent request, automatically navigate
  to OAuth, or replay a task after reconnection.
- Setup deficiencies, cancellation, missing grants, unknown verification state,
  token failure, and organization-policy denial are not conflated.
- Permission loss prevents affected capabilities from continuing on stale evidence.
- Unaffected usable capabilities are not presented as failed solely because
  another permission was withheld.
- Closing setup is distinguished from disconnecting a saved connection, revoking
  Google consent, or reversing already completed provider effects.

### REQ-8. Existing authority and security boundaries

Retain the existing connection ownership, management permissions, and execution
model while making the implications of account sharing clear.

**Acceptance criteria**

- Agent-only and Workspace-shared connections remain within current management
  authority; configuration visibility does not grant execution authority.
- Authorized Team runs use the connected account; no user identity is inferred
  from a Discord sender or substituted into execution.
- Final review warns that shared execution uses the connected account, not each
  participant's private account.
- Private tokens and data are protected; external emails, documents, and events
  are treated as untrusted content under applicable provider security policies.

### REQ-9. Accessible and truthful setup UI

Offer readable, recoverable setup and accurate task-level state at desktop and
mobile sizes, consistent with the existing connection experience.

**Acceptance criteria**

- Controls, error messages, verification states, and recovery are keyboard-usable
  and accessible without horizontal overflow.
- Explicit progression preserves context and respects reduced-motion preferences;
  background refreshes do not unexpectedly move the user.
- Product copy is localized and avoids raw permission-code-first explanations.
- Explanatory mock examples are not presented as live account or access evidence.

## Fixed Constraints

- Google official remote MCP is the selected service integration direction.
- Operators provide their own Google authorization application and comply with
  Preview eligibility, audience restrictions, and service policies.
- No automatic infrastructure change, Google account authorization, or production
  deployment is authorized by the technical-design request.
- Preserve existing generic MCP, GitHub, Notion, Sentry, and Toolkit contracts
  unless a separately confirmed requirement authorizes a change.
- Existing data preservation obligations remain; no unrequested legacy fallback
  or product version history is introduced.

## Open Assumptions and Product Boundaries

The following remain unresolved and are not implementation authority:

- Whether operator application settings are reusable across connections, whether
  managers may bring their own application, and the management entry for each.
- Initial service/task defaults and the supported task catalog beyond the three
  named services; examples are not the full feature contract.
- Whether services in one Google connection must use the same Google account.
- The explicit user experience for updating a saved connection with reduced
  grants through ordinary reconnect, and the effect of resetting or closing
  while a write is in progress. This is not authority for a separate consent UI.
- The exact provider-supported scope-to-tool mappings and grant verification
  evidence. Documentation alone does not establish live interoperability.
- The provider-policy-compatible prompt/response screening and risk-disclosure
  approach. No paid security service is selected by this snapshot.

## Confirmation

The requester asked to proceed to technical design on 2026-10-13 after selecting
the unified Google experience and requiring partial-consent handling. This request
starts requirements translation and technical investigation; explicit confirmation
of this repository Requirements snapshot is pending. No ADR decisions or primary
Design approval have been recorded, and implementation has not started.

The requester subsequently clarified that the original scope is Google connection
setup with truthful partial-consent handling, not a new additional-consent feature,
and affirmed that correction on 2026-10-13. This clarification removes the
assistant-added per-capability consent workflow; it is not a scope reduction.
