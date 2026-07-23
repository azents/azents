---
title: "Platform Runtime Provider Management"
created: 2026-07-22
tags: [architecture, runtime, provider, admin, platform, security, infra]
document_role: primary
document_type: adr
snapshot_id: provider-260722
---

# provider-260722/ADR: Platform Runtime Provider Management

## Requirements

This ADR records hard-to-reverse architecture decisions for the confirmed [Platform Runtime Provider Management Requirements](../requirements/provider-260722-platform-runtime-provider-management.md) (`provider-260722/REQ`).

Accepted decisions are recorded below. Remaining decision points stay pending until the requester selects an option or adjusts the direction.

## Context

A Provider is the external automation boundary that provisions, observes, reconciles, and deprovisions Agent-dedicated Runtime incarnations. A Provider is not required for a user-provisioned Runtime that runs the common Runner directly. Every Provider is external to the Azents control-plane processes even when it is developed in the same repository or deployed through the same Helm release.

The first delivery must implement Platform Admin registration as the primary flow and Helm auto-registration through the same product resource and lifecycle. Kubernetes is the first concrete Platform Provider. Workspace Providers, user-provisioned Runtime enrollment, and Session-dedicated logical Runtimes remain future snapshots.

### Requirements scope clarification: bootstrap is adapter-neutral

The requester reconfirmed `provider-260722/REQ` on 2026-07-22 with trusted Provider bootstrapping as a general product capability. Helm auto-registration is the first adapter and concrete deployment scenario, not the domain-level registration mechanism. Architecture decisions after D1 therefore use bootstrap-source terminology and must allow future trusted adapters without redefining Provider identity, Admin management, connection, matching, or Runtime lifecycle behavior.

## Current System Evidence

### Runtime Provider persistence is an unused skeleton

`runtime_providers` currently stores a globally unique logical ID, `system|workspace` scope, `kubernetes|docker` implementation kind, display name, enabled flag, capabilities, config schema, metadata, and an optional Workspace ID. The repository can create, list, and enable rows, but no service, Admin API, Public API, startup reconciliation, or Provider connection path creates or manages these resources.

The current shape does not represent:

- Platform ownership terminology;
- Admin versus deployment registration source;
- administrative lifecycle such as disabled, decommissioning, decommissioned, or force-retired;
- platform-wide versus selected-Workspace availability;
- enrollment credentials or credential rotation;
- desired, accepted, active, and Runtime-applied configuration revisions;
- Provider capability compatibility history;
- deployment presence and Helm reconciliation state; or
- Provider-level readiness, capacity, or last-observed state.

### Agent Runtime provides a strong logical Runtime base

`agent_runtimes` has one durable row per Agent and stores desired lifecycle generation, Provider observed generation and state, Runner generation and state, workspace path, failure summary, and terminal Provider deletion acknowledgement. Runtime Control reconciliation is generation-fenced and external Provider and Runner streams use distributed coordination.

However, the Provider binding is a nullable string without a foreign key or resource validation. The existing environment-backed default is copied into Agents and Agent Runtimes without checking Provider existence, availability, capability, or readiness. `provider_config` is unversioned JSON without a typed policy source or applied-revision contract.

### Provider Control accepts connection identity without durable binding

The external Provider stream authenticates with one optional shared Runtime Control token. The registration payload supplies `provider_id`, type, scope, capabilities, schema version, metadata, and `auth_credential_id`, but the server records these values directly in the coordination store. It does not resolve a known Provider resource, validate a Provider-specific credential, compare registration claims with durable policy, or prevent an authenticated client from claiming another Provider ID.

Provider reports validate Runtime existence and generations but do not currently verify that the report's Provider ID is the immutable Provider bound to that Runtime.

### Kubernetes Provider is external but entirely environment-configured

The Kubernetes Provider is already an external process that uses the shared Provider Control contract and the common Runner. It supports provision, observe and resynchronize, stop, restart, reset, terminal deletion, Kubernetes Pod replacement, and PVC-backed Workspace persistence.

Its Provider ID, namespaces, storage class and size, Runner resources and limits, Pod metadata and scheduling fields, image references, and Runtime Control credentials are loaded only from environment variables at process startup. It has no channel for receiving Provider configuration revisions, validating a candidate against the Kubernetes backend, acknowledging an active revision, or reporting per-Runtime applied revisions.

### Helm currently bypasses the future Admin resource lifecycle

When the Kubernetes Provider is enabled, Helm deploys the controller and injects its ID and settings directly. Helm also injects the same Provider ID into the server as `AZ_RUNTIME_DEFAULT_PROVIDER_ID`. There is no durable Provider descriptor reconciliation and no Admin-visible deployment presence, field ownership, conflict, or removal state.

The Runtime Provider controller receives the shared Runtime Control token through an existing Secret reference when shared auth is enabled. `AZ_RUNTIME_PROVIDER_AUTH_CREDENTIAL_ID` currently contains the Provider ID rather than a credential issued for one known Provider registration.

### System Settings provides reusable lifecycle patterns, not the Provider aggregate

System Settings implements typed compiled singleton Sections with optimistic revision, candidate validation and confirmation, encrypted secrets, environment overlays, health, audit events, and operation-boundary resolution. These mechanisms provide useful patterns and reusable services for configuration lifecycle.

The current registry and tables are keyed by a compile-time Section enum and assume one instance-wide value per Section. They do not directly model multiple dynamic Provider resources, Provider connections, availability, capability history, or administrative lifecycle. Treating the complete Provider aggregate as a System Settings Section would conflate resource identity and operational lifecycle with configuration values.

### User interfaces are absent

Admin Web has a System Settings surface but no Runtime Provider inventory or detail page. The main Web Agent form carries the generated `runtime_provider_id` field in API models but does not present Provider discovery, eligibility, capability, persistence, policy, or immutable-binding controls.

## Initial Feasibility Matrix

| Requirement area | Result | Evidence and gap |
| --- | --- | --- |
| External Provider and common Runner | Feasible | Kubernetes and Docker Providers already use the shared external protocol and common Runner. |
| Agent-dedicated logical Runtime | Feasible | One durable `agent_runtimes` row per Agent and generation fencing already exist. |
| Admin registration and enrollment | Conditional | Admin auth and resource API patterns exist; Provider resource service and credential lifecycle are missing. |
| Helm auto-registration parity | Conditional | Helm can render a descriptor, but server-side descriptor reconciliation and ownership conflict handling are missing. |
| Optional Provider installation | Feasible | Chart defaults Provider and Runtime Control off; Runtime absence already produces explicit unavailable states in parts of the flow. |
| Workspace availability and default selection | Conditional | Workspace and Agent ownership data exist; Provider availability and validated selection services are missing. |
| Provider configuration revisions | Conditional | System Settings provides revision, validation, impact, secret, and audit patterns; dynamic Provider-scoped configuration is missing. |
| Core lifecycle and optional capabilities | Conditional | Core Kubernetes lifecycle exists; the protocol currently assumes a fixed lifecycle surface and untyped capability strings. |
| Provider-specific persistence | Feasible | Kubernetes demonstrates persistent PVC semantics; the protocol can be extended to declare ephemeral or other behavior. |
| Decommission and force retire | Conditional | Terminal per-Runtime cleanup exists; Provider administrative lifecycle and dependency projection are missing. |
| Kubernetes first implementation | Feasible | Provider, tests, Helm component, RBAC, NetworkPolicy, and Runtime Pod rendering already exist. |
| Admin and Agent UI | Conditional | Established Admin and Agent feature patterns exist; Provider-specific routes, generated clients, and UI are missing. |

No repository blocker prevents the confirmed Requirements. The primary work is authority and lifecycle modeling rather than proving Kubernetes provisioning viability.

The Helm feasibility entry above evaluates the first concrete bootstrap adapter. The repository does not yet contain an adapter-neutral bootstrap declaration contract, source identity, trust boundary, or reconciliation lifecycle.

## Decisions

### provider-260722/ADR-D1: Use a first-class Provider aggregate with Provider-scoped configuration

**Affected requirements:** `provider-260722/REQ-3`, `REQ-5`, `REQ-8`, `REQ-9`, `REQ-14`, `REQ-16`, `REQ-20`

A Provider is a first-class durable operational aggregate. Provider identity, ownership scope, registration source, Workspace availability, administrative lifecycle, enrollment, connection projection, capability contract, deployment presence, and bound-Runtime dependency projection belong to the Provider domain.

Provider configuration belongs to that Provider and has an independent resource-scoped revision lifecycle. Revision, candidate validation, confirmation, encrypted secret, impact, health, and audit mechanisms must reuse or extract the generic lifecycle patterns established by System Settings, but Provider identity and operational state are not System Settings values.

The singleton System Settings domain retains only genuinely instance-wide policy, including the default Platform Provider and any future global Runtime policy that is not owned by one Provider.

**Rationale:**

- Multiple Providers need independent identity, connection, lifecycle, configuration revision, validation, health, and audit history.
- Agent Runtime bindings and decommission dependencies refer to a durable Provider resource, not to a configuration Section or a key inside a shared JSON map.
- Admin and Helm registration can converge on one Provider aggregate while retaining source-specific field ownership.
- The same aggregate can later represent Workspace Providers without turning System Settings into a generic resource manager.
- Existing System Settings lifecycle machinery remains valuable and should be reused at the mechanism level rather than by conflating its singleton domain model with Providers.

**Rejected alternatives:**

- Dynamic System Settings Sections were rejected because the current compile-time singleton registry would need to become a generic resource manager and would mix connection and lifecycle state with settings.
- One singleton System Settings map containing all Provider configuration was rejected because unrelated Providers would share revisions and candidates, creating update conflicts and separating each Provider's lifecycle from its configuration audit.

**Consequences:**

- The Provider domain requires durable aggregate, configuration-revision, candidate, health, audit, and dependency projections.
- Generic configuration lifecycle code may be extracted from System Settings, but the existing singleton tables and Section enum are not the Provider source of truth.
- Admin APIs and UI use Provider inventory and detail resources rather than presenting Providers as System Settings Sections.

**Subsequent scope clarification:**

- D1 applies equally to Admin-created Providers and Providers established by any trusted bootstrap adapter.
- The Helm reference in the rationale identifies the first concrete adapter only. It does not grant Helm-specific ownership in the Provider domain.

### provider-260722/ADR-D2: Reconcile durable bootstrap declarations into the Provider aggregate

**Affected requirements:** `provider-260722/REQ-3`, `REQ-4`, `REQ-5`, `REQ-14`, `REQ-20`

Trusted Provider bootstrap uses an adapter-neutral durable Bootstrap Declaration that is separate from both the Provider aggregate and a running Provider controller connection. Each declaration is identified by an authenticated bootstrap source identity and a stable declaration key within that source. Helm is the first adapter that supplies declarations through this contract; adapter type and transport are not part of Provider identity.

Azents reconciles each active declaration into the same first-class Provider aggregate used by Admin registration. A Provider established through bootstrap is not a separate product resource type and uses the same Admin inventory, configuration, connection, matching, Runtime binding, lifecycle, and audit behavior.

Bootstrap field ownership is divided as follows:

- The bootstrap declaration owns its source identity, declaration key, canonical Provider ID, Provider implementation type, registration source, source revision, and declaration-presence state.
- Platform Admin owns product policy after creation, including enabled state, display-name override, Workspace availability, Provider product configuration, decommissioning, and forced retirement.
- A declaration may seed allowed Admin-owned values only when it first creates the Provider. Reconciliation does not reapply those seed values after creation or overwrite later Admin changes.
- Provider-observed capabilities, schema compatibility, connection state, readiness, capacity, and applied configuration state are supplied through the authenticated Provider connection rather than controlled by bootstrap.

Reconciliation follows these identity and lifecycle rules:

- Repeating the same source identity, declaration key, Provider ID, and implementation type is idempotent.
- Reusing a declaration identity with different immutable Provider identity fields is a conflict and does not mutate the existing Provider.
- Claiming a Provider ID already owned by Admin or another bootstrap declaration is a conflict. Bootstrap never performs implicit ownership adoption.
- Replacing an adapter does not replace the Provider when the new adapter authenticates as the same bootstrap source and retains the declaration key.
- The first delivery does not merge multiple registration owners into one Provider. Transferring a Provider to another source requires a future explicit adoption flow or a new Provider identity.
- A trusted source explicitly withdrawing a declaration, or omitting it from an authoritative source revision, marks the declaration absent. Bootstrap transport failure and Provider controller disconnection do not by themselves imply withdrawal.
- Declaration absence does not delete the Provider, Admin configuration, enrollment history, logical Runtime bindings, cleanup evidence, or external infrastructure.
- Returning the same source and declaration identity restores declaration presence on the existing Provider without reapplying creation-time seed values.
- A force-retired Provider and its registration identities remain reserved. A later declaration cannot reactivate it without an explicit future Admin recovery operation.

**Rationale:**

- Durable declaration identity makes install, retry, upgrade, removal, reinstall, and adapter replacement deterministic.
- Separating deployment intent from the Provider aggregate preserves independent Admin policy and lifecycle.
- Separating bootstrap from controller connection prevents authenticated Provider processes from discovering or creating their own trusted identity.
- An adapter-neutral contract lets Helm, installation tooling, or future operators supply the same product intent without introducing adapter-specific Provider models.

**Rejected alternatives:**

- Direct idempotent Provider upsert by each bootstrap adapter was rejected because source presence, removal, reinstall, field ownership, and adapter replacement would be encoded inconsistently inside the Provider aggregate or reimplemented by every adapter.
- Control-plane startup configuration as the only bootstrap mechanism was rejected because it would couple generic Provider bootstrap to server deployment and restart behavior and would make future adapters second-class.
- Provider controller self-registration remains disallowed because connection authority must bind to a known Provider rather than create one.

**Consequences:**

- The Provider domain requires a durable Bootstrap Declaration source of truth and reconciliation history.
- Bootstrap source authentication is a narrow authority separate from Platform Admin, Provider controller, Runtime Runner, and Runtime-scoped credentials.
- Bootstrap adapters must preserve source and declaration identity across retries and upgrades.
- The exact declaration transport and first Helm adapter delivery mechanism remain Design concerns as long as they implement this identity and reconciliation contract.

### provider-260722/ADR-D3: Exchange one-time enrollment grants for Provider-specific credentials

**Affected requirements:** `provider-260722/REQ-3`, `REQ-4`, `REQ-9`, `REQ-10`, `REQ-12`, `REQ-14`, `REQ-20`

Controller enrollment uses a short-lived, single-use grant bound to exactly one known Provider. Azents issues the grant through an authorized Platform Admin operation or, for a bootstrapped Provider, through the narrow authority of the bootstrap source that owns the corresponding declaration. Bootstrap authority cannot request enrollment for an Admin-owned Provider or for another source's declaration.

The Provider controller exchanges the grant for a Provider-specific opaque credential. The credential secret is returned only during issuance, is stored by the controller's deployment through an operator-controlled secret mechanism, and is retained only as a verification hash by Azents. The enrollment grant becomes unusable after successful exchange or expiry.

Every Provider Control connection authenticates with an active Provider credential over an authenticated encrypted transport. Azents resolves the durable Provider identity from the credential binding. A `provider_id`, implementation type, credential ID, or other identity claim in the connection payload is validated against that binding and cannot select or create a different Provider.

Provider credentials have their own durable identity, status, issuance actor, creation time, optional expiry, last-used observation, and revocation history. A Provider may temporarily have more than one active credential so an operator can issue a replacement, establish a new connection, and then revoke the old credential without an avoidable control-plane outage.

Authority boundaries are strict:

- Bootstrap source credentials can declare Providers and request enrollment only within their declaration ownership.
- Enrollment grants can perform one enrollment exchange for their bound Provider and no other operation.
- Provider credentials can authenticate Provider Control connections only for their bound Provider.
- Runtime Runner and Runtime-scoped control credentials remain bound to their own Runtime identity and cannot authenticate as a Provider.
- Platform Admin credentials are not installed in Provider controller deployments.
- A shared gateway or transport-access credential, if an operator deploys one as defense in depth, is not Provider identity and cannot substitute for the Provider-specific credential.

Revoking one Provider credential terminates or rejects connections authenticated by that credential without deleting the durable Provider. Disabling or decommissioning a Provider prevents new enrollment unless an explicit lifecycle operation permits rotation for cleanup. Force retirement revokes every enrollment grant and Provider credential and prevents later bootstrap or connection activity from reactivating the Provider.

Credential delivery and durable secret storage are deployment-operator or bootstrap-adapter responsibilities. This decision does not grant the Provider controller permission to mutate Kubernetes Secrets, deployment RBAC, or other infrastructure security boundaries.

**Rationale:**

- A one-time grant limits the value and lifetime of installation material while keeping long-lived connection authority independently revocable.
- Provider-specific credentials let the server derive identity from authenticated state instead of trusting client registration claims.
- Overlapping credentials provide a practical rotation path for Kubernetes and external Provider deployments.
- Opaque credentials work through common gRPC and ingress topologies without requiring Azents to operate a client-certificate PKI.

**Rejected alternatives:**

- Issuing a long-lived Provider token directly during registration was rejected because it would expose durable connection authority during the broader installation flow and would not distinguish unused enrollment from an active controller credential.
- Mandatory mTLS client certificates were rejected for the first common contract because certificate authority operation, certificate renewal, and proxy termination requirements would make external Provider deployment substantially more complex. Deployment-level mTLS may still be used as defense in depth.
- The existing shared Runtime Control token is rejected as Provider identity because any holder could otherwise claim another Provider ID and Provider-specific rotation or revocation would be impossible.

**Consequences:**

- The Provider domain requires enrollment-grant and Provider-credential records with secure hashing, expiry, single-use exchange, rotation, revocation, and audit behavior.
- Provider Control authentication must complete before accepting registration claims or Provider reports.
- Existing shared-token-only Provider connections require an explicit migration and cutover in D8; they are not a permanent compatibility fallback.
- Bootstrap adapter design must include a secure way to deliver enrollment material and persist the issued Provider credential without moving infrastructure security control into the Admin product surface.

### provider-260722/ADR-D4: Validate Provider-proposed contracts and require Admin acceptance

**Affected requirements:** `provider-260722/REQ-8`, `REQ-9`, `REQ-10`, `REQ-11`, `REQ-13`, `REQ-15`, `REQ-16`, `REQ-17`, `REQ-18`

Azents owns the capability and configuration meta-contract. It defines the mandatory core lifecycle, standardized optional capability vocabulary, extension naming rules, configuration field types, validation vocabulary, supported policy scopes, secret markers, application-impact semantics, Workspace persistence semantics, compatibility rules, and protocol versions that the product can safely interpret.

An authenticated Provider controller proposes an immutable, versioned Capability Contract containing its implementation identity and version, protocol version, core and optional capabilities, Workspace persistence behavior, configuration schema, policy scopes, and configuration application semantics. Azents canonicalizes the semantic content and computes a digest so reconnects and upgrades can be compared independently of presentation or transport metadata.

Azents validates every proposed contract before presenting it for acceptance:

- The mandatory core lifecycle and protocol compatibility must pass machine validation and cannot be waived by an Admin.
- Configuration schemas use a restricted declarative vocabulary. They cannot include executable UI content or expose deployment infrastructure controls such as Kubernetes RBAC, RuntimeClass mutation, admission policy, or an unrestricted privileged toggle.
- Optional extensions must be namespaced and remain within the supported meta-contract. Unknown executable behavior is not inferred from a display label or arbitrary metadata.
- A Provider can declare only what it implements. Admin policy may restrict an accepted capability but cannot add unsupported capability.

The first valid contract for a Provider becomes a candidate and requires Platform Admin acceptance before the Provider is provisioning-ready. An identical contract digest on reconnect requires no new acceptance. A semantic change to capabilities, persistence behavior, configuration fields or ranges, policy scopes, application timing, replacement requirements, or compatibility behavior creates a new candidate revision and does not silently replace the accepted contract.

The durable Provider state distinguishes the last accepted contract, the contract currently observed from the connected controller, and any pending candidate. If a new controller no longer implements the accepted contract, Azents preserves the accepted snapshot for audit and policy interpretation but marks the Provider contract-mismatched and blocks new provisioning until an Admin accepts a compatible candidate or the controller is rolled back. Mutually compatible core cleanup and observation operations may remain available so contract review does not strand existing infrastructure.

Accepting a contract records that the product may use that Provider contract. It does not silently mutate existing Runtime policy, claim that an existing incarnation has adopted new configuration, or trigger replacement. Configuration revision delivery and per-Runtime adoption are decided in D6.

Connection state, transient health, readiness, current capacity, last observation, and applied configuration revision are operational observations rather than Capability Contract changes and update without Admin acceptance.

**Rationale:**

- Provider-owned contracts allow independently deployed and future third-party Provider implementations without requiring every schema revision to ship in the Azents server.
- Azents-owned meta-contract validation prevents an external schema from redefining product security boundaries or introducing behavior the control plane cannot interpret.
- Durable candidate and accepted revisions prevent a Provider upgrade from silently changing Admin policy, UI, persistence guarantees, or existing Runtime compatibility.
- Separating semantic contract revisions from telemetry avoids approval churn for normal operational state changes.

**Rejected alternatives:**

- A server-owned static registry for every Provider implementation was rejected because Provider upgrades would require coordinated Azents server releases and future external Providers would remain second-class.
- Treating the latest live Provider report as immediately authoritative was rejected because a deployment error or upgrade could silently remove capabilities, change persistence semantics, or invalidate policy and existing Runtimes.

**Consequences:**

- The Provider domain requires immutable candidate and accepted Capability Contract revisions, canonical semantic digests, validation results, Admin acceptance audit, and observed-versus-accepted compatibility state.
- Provider Control registration must carry enough versioned contract information to validate the implementation before readiness is granted.
- Admin UI must show contract differences and distinguish protocol rejection, pending acceptance, accepted compatibility, and observed mismatch.
- The accepted contract remains available while the Provider is disconnected.

### provider-260722/ADR-D5: Bind the Provider atomically when the logical Runtime is created

**Affected requirements:** `provider-260722/REQ-1`, `REQ-6`, `REQ-7`, `REQ-9`, `REQ-10`, `REQ-15`, `REQ-17`, `REQ-19`, `REQ-20`

Provider availability is durable product policy. Each Platform Provider has either platform-wide availability or selected-Workspace availability represented by explicit Provider-to-Workspace memberships. Availability changes affect eligibility for new logical Runtime bindings and do not rewrite or remove existing bindings.

The Platform default Provider remains a genuinely instance-wide System Setting that references a durable Provider. An Agent may hold a nullable explicit Provider preference before its logical Runtime exists. The Agent preference and Platform default are candidate-selection inputs rather than Runtime bindings.

Azents resolves and writes the Provider binding in the logical Runtime creation transaction:

1. Read and protect the relevant Agent, Workspace, explicit preference, Platform default, Provider, availability, lifecycle, accepted Capability Contract, and applicable policy revisions from concurrent conflicting changes.
2. Use the explicit Agent preference when present; otherwise use the Platform default.
3. Validate that the exact candidate is enabled for new use, available to the Workspace, contract-compatible, connected and provisioning-ready, and capable of satisfying the required Runtime and persistence policy.
4. If the explicit candidate is ineligible, return its specific failure instead of trying the default or another Provider. If the default is absent or ineligible, return an explicit unavailable result without arbitrary fallback.
5. On success, create the logical Runtime and its Provider binding atomically before dispatching external provisioning.

A Provider-provisioned logical Runtime stores a durable Provider foreign-key reference, the selection source, binding time, and the accepted contract and policy evidence used for the decision. The Provider reference is write-once for that logical Runtime. Product APIs and domain services do not expose reassignment, and durable Provider deletion is restricted while bindings or retained cleanup history reference it.

A future user-provisioned logical Runtime uses an explicit provisioning-origin discriminator and has no Provider binding. Provider nullability is therefore interpreted through provisioning origin rather than as an unvalidated missing reference.

Agent preference edits, Platform default changes, Workspace availability edits, Provider disablement, and later capability or policy changes do not rebind an existing logical Runtime. Using another Provider requires explicitly ending the logical Runtime according to its persistence and cleanup semantics and creating a new one.

Readiness and capacity are externally changing observations. Azents uses the latest eligible observation before committing a binding, but the Provider remains the final authority for provisioning admission. If capacity or readiness changes after the transaction and the Provider rejects the request, the logical Runtime remains bound to that Provider in an explicit blocked or pending state. Azents does not retry the request on another Provider and does not claim that a physical incarnation was created.

**Rationale:**

- Binding at logical Runtime creation makes ownership, cleanup responsibility, persistence semantics, and future incarnation replacement deterministic.
- Keeping Agent preference separate from Runtime binding avoids stale pre-assignment resources and lets current eligibility be validated at the actual provisioning boundary.
- One transaction prevents concurrent Admin policy changes from producing a Runtime whose initial binding was never valid under one coherent policy view.
- Retaining the failed Provider binding after a post-commit admission race preserves the no-migration rule and makes remediation explicit.

**Rejected alternatives:**

- A separate durable Agent-to-Provider assignment before Runtime creation was rejected because it would duplicate preference and binding lifecycles, become stale as defaults or availability change, and still require validation when the Runtime is created.
- Resolving a Provider dynamically for every provisioning, restart, or replacement command was rejected because the Provider could change during one logical Runtime's lifetime, breaking infrastructure ownership and Workspace persistence semantics.

**Consequences:**

- Provider availability memberships, the Platform default reference, Agent preference, logical Runtime provisioning origin, and immutable Provider binding require referentially validated persistence.
- Runtime creation needs transactional eligibility resolution and auditable decision evidence.
- UI must distinguish a pre-Runtime Agent preference from an existing Runtime's immutable Provider binding.
- Operational lifecycle rules for a bound Runtime after disablement, contract change, or decommissioning remain part of D6 and D7.

### provider-260722/ADR-D6: Activate validated configuration revisions and apply immutable Runtime policy snapshots

**Affected requirements:** `provider-260722/REQ-8`, `REQ-9`, `REQ-10`, `REQ-15`, `REQ-16`, `REQ-17`, `REQ-18`

Provider product configuration and Platform Runtime policy use immutable Provider-scoped revisions. An Admin edit creates a candidate from an explicit active base revision rather than mutating the active value. Optimistic concurrency prevents a candidate based on stale configuration from overwriting a newer revision.

Candidate processing is a two-stage validation and explicit activation flow:

1. Azents validates field types, required values, capability limits, supported policy scopes, Platform constraints, secret handling, application semantics, and compatibility with the accepted Capability Contract revision.
2. Azents sends the candidate over the authenticated Provider Control connection for backend-specific validation without authorizing the Provider to apply it.
3. The Provider returns accepted, rejected, accepted-with-impact, or temporarily-unable-to-validate status with field-level validation and Runtime-impact information.
4. A Platform Admin reviews the result and explicitly confirms activation. Provider validation alone does not make the candidate active.
5. Azents delivers the active revision to the Provider as desired state, and the Provider acknowledges which revision it has received and made active at Provider level.

Provider disconnection leaves a valid candidate waiting for validation and preserves the previous active revision. Candidate rejection or activation-delivery failure does not silently mutate or roll back the durable desired revision. Admin surfaces distinguish candidate, Azents-validated, Provider-accepted, active desired, Provider-active, and rejected or divergent states.

Provider configuration and Runtime policy secrets are encrypted at rest, redacted from Admin readback and audit payloads, and delivered only to the Provider or Runtime boundary that requires them. Provider reports cannot echo secret plaintext. Provider controller credentials and Provider-level secrets are never passed to Runtime Runner or sandbox containers.

Effective Runtime policy resolves in this order:

1. The accepted Provider Capability Contract defines the technical maximum and supported policy scopes.
2. Platform Admin policy defines defaults and allowed constraints within that contract.
3. Agent overrides replace supported values within Platform constraints and otherwise inherit Platform defaults.
4. A future Session policy may override supported Agent policy within the same Provider and Platform limits.

Unsupported values and out-of-range overrides are rejected rather than clamped or replaced. Effective values retain source traceability so an authorized user can distinguish Provider capability, Platform default or constraint, Agent override, and future Session override.

Before provisioning a new incarnation or applying a supported live change, Azents creates an immutable Runtime Policy Snapshot. The snapshot contains the Provider binding, accepted Capability Contract revision, active Provider configuration revision, Platform policy revision, Agent override revision, future Session revision when applicable, resolved values, source trace, and canonical digest. Provider commands reference this snapshot, and Provider reports identify the snapshot accepted and the revision actually applied to each Runtime incarnation.

Application follows the semantics declared by the accepted Capability Contract:

- Immediate settings may be applied to the current incarnation and require a per-Runtime success or failure acknowledgement.
- Next-incarnation settings remain pending for the current incarnation and are included when it is next created.
- Replacement-required settings mark the Runtime with an observable requirement and reason. Saving or activating ordinary configuration does not itself replace the incarnation.
- New-logical-Runtime-only settings do not change an existing logical Runtime.
- Immutable settings reject changes at the lifecycle stage where mutation is no longer allowed.

Automatic replacement occurs only when the Provider declares the capability and the effective lifecycle policy enables it. A compatibility-required replacement cannot be permanently suppressed by Agent policy; Platform policy may control safe timing or a deadline, and the Runtime remains explicitly incompatible or blocked until replacement or external remediation.

If external readiness or capacity changes after validation, the Provider may reject application with a current reason. Azents preserves desired, Provider-active, and Runtime-applied divergence rather than reporting the desired revision as successfully applied.

**Rationale:**

- Two-stage validation catches both schema-level errors and backend conditions known only to the external Provider before activation.
- Explicit Admin activation makes impact, replacement, and persistence consequences reviewable.
- Immutable source-traced Runtime snapshots make retries, reconnects, incarnation replacement, and audit deterministic.
- Separating Provider-active from Runtime-applied revisions prevents configuration storage from being mistaken for successful physical application.

**Rejected alternatives:**

- Activating immediately after Azents-only validation was rejected because backend-specific rejection and replacement impact would be discovered only after the product claimed the revision was active.
- Directly pushing one mutable configuration document was rejected because requested, validated, active, Provider-loaded, and Runtime-applied states would be indistinguishable and reconnect or rollback behavior would be ambiguous.

**Consequences:**

- Provider configuration revisions, validation attempts, activation records, secret values, Runtime Policy Snapshots, source traces, and Provider or Runtime acknowledgements require durable persistence.
- Provider Control needs candidate-validation, active-revision delivery, resynchronization, and per-Runtime applied-snapshot messages.
- Admin and Agent UI must show effective values, their sources, expected impact, revision divergence, and replacement requirements.
- D7 must preserve these revisions and Runtime application records through decommissioning and forced retirement.

### provider-260722/ADR-D7: Use an explicit lifecycle state machine and durable cleanup dependency ledger

**Affected requirements:** `provider-260722/REQ-3`, `REQ-7`, `REQ-9`, `REQ-10`, `REQ-14`, `REQ-15`, `REQ-18`, `REQ-20`

Provider administration separates reversible enablement policy, permanent lifecycle, and operational conditions:

- Enablement policy is enabled or disabled while the permanent lifecycle is active.
- Permanent lifecycle is active, decommissioning, decommissioned, or force-retired.
- Operational conditions independently describe bootstrap presence, connection, accepted-contract compatibility, provisioning readiness, capacity, configuration divergence, and cleanup progress.

Disconnection, bootstrap declaration absence, capacity exhaustion, or contract mismatch does not implicitly disable, decommission, or delete a Provider.

Disabling a Provider blocks new Agent selection, new logical Runtime bindings, and provisioning of new physical incarnations. It does not stop an active Runner or delete infrastructure. Observation and non-creating cleanup operations remain available, and an active Provider may be enabled again.

Decommissioning is an explicit, irreversible permanent-lifecycle transition from an enabled or disabled active Provider. Before confirmation, Admin shows bound logical Runtimes, affected Workspaces, known physical incarnations and external resource references, Workspace persistence and data-loss consequences, pending configuration or replacement state, bootstrap declaration state, connection and credential state, and the cleanup plan. Temporary pauses use disablement rather than entering decommissioning.

Starting decommissioning creates or refreshes a durable Cleanup Dependency Ledger. Each dependency records the Provider and logical Runtime identity, last known incarnation and external infrastructure references, persistence consequence, cleanup operation identity and generation, requested and observed terminal state, Provider evidence, and one of pending, in-progress, verified-clean, failed, or unverified status.

While decommissioning:

- New matching, binding, enrollment, and provisioning are blocked.
- Existing Provider credentials may operate in cleanup-only mode, and explicit credential rotation is allowed only when required to complete cleanup.
- Each affected logical Runtime follows an explicit ending flow; Azents does not migrate it or select another Provider.
- Deprovision requests and reports remain generation-fenced and idempotent.
- Provider terminal evidence is retained per dependency.
- After Runtime-level cleanup, the Provider must complete a full resynchronization barrier and report Provider-level terminal cleanup acknowledgement for the infrastructure it owns.

Normal decommissioning completes only when every required dependency has verified terminal cleanup evidence and no active Provider-owned infrastructure remains in the final reconciliation result. Azents then revokes remaining enrollment grants and Provider credentials, closes control connections, and marks the Provider decommissioned. The Provider identity, historical bindings, configuration, contract revisions, cleanup evidence, and audit history remain durable and cannot be reused or re-enabled.

If the Provider is permanently unreachable or cannot provide the required evidence, a Platform Admin may explicitly force retire it from decommissioning after reviewing every unresolved dependency and cleanup uncertainty. Force retirement immediately revokes enrollment and Provider credentials, rejects existing and future connections, blocks every new operation, records unresolved dependencies as unverified rather than successful, and preserves logical Runtime bindings, external resource references, and audit history. Later external cleanup evidence may be attached for operational recordkeeping but does not reactivate the Provider or rewrite the force-retirement decision.

For a bootstrapped Provider, explicit declaration withdrawal or omission from an authoritative source revision records bootstrap absence and immediately blocks new selection and provisioning. It does not delete the Provider, revoke credentials, stop active Runners, claim cleanup, or enter decommissioning. A still-connected controller may perform cleanup. Returning the same declaration identity restores presence only while the Provider lifecycle remains active and still requires enabled, contract-compatible, and ready conditions. An active declaration cannot reverse decommissioning, decommissioned, or force-retired lifecycle.

**Rationale:**

- Separating policy, lifecycle, and observations prevents transient deployment or network failures from becoming destructive administrative actions.
- A durable dependency ledger makes decommission retries, reconnects, generation fencing, and cleanup evidence auditable.
- A final resynchronization barrier avoids treating isolated command acknowledgements as proof that no Provider-owned infrastructure remains.
- Force retirement preserves an honest distinction between ending Azents trust and verifying external resource deletion.

**Rejected alternatives:**

- Deriving decommission progress only from current Runtime rows and live Provider reports was rejected because disconnects, concurrent changes, and retries would erase which dependencies were verified or remained uncertain.
- Automatically deleting or decommissioning on Provider disconnect or bootstrap withdrawal was rejected because transient failure or Helm removal could destroy product identity without verified external cleanup.

**Consequences:**

- Provider lifecycle, enablement, operational conditions, Cleanup Dependency Ledger entries, evidence, reconciliation barriers, and terminal audit require durable persistence.
- Provider Control needs an explicit cleanup-only authorization mode and terminal reconciliation evidence.
- Decommissioned and force-retired Provider identities remain reserved; routine physical deletion is not part of this snapshot.
- D8 must preserve existing Runtime bindings and cleanup uncertainty during migration rather than manufacturing successful terminal evidence.

### provider-260722/ADR-D8: Use a narrow bootstrap-and-binding cutover without a legacy compatibility mode

**Affected requirements:** `provider-260722/REQ-3`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-8`, `REQ-10`, `REQ-13`, `REQ-14`, `REQ-20`

Read-only inspection of the deployed home database on 2026-07-22 found that `runtime_providers` contains no rows. Three Agents and their three logical Agent Runtimes reference the string Provider ID `system-kubernetes`; all three Runtimes report connected Provider state and running observed state, and none has non-empty `provider_config`.

The migration therefore does not build a generic import or ownership-adoption system for the unused `runtime_providers` skeleton. It uses a narrow, fail-closed cutover for the existing Kubernetes Provider identity and rejects unexpected data for explicit operator resolution.

Executed database migrations remain immutable. New additive migrations introduce the first-class Provider aggregate, Bootstrap Declaration, Capability Contract revisions, enrollment and Provider credentials, Workspace availability, configuration revisions, Runtime Policy Snapshots, immutable Runtime Provider foreign keys, administrative lifecycle, and cleanup ledger. Legacy string columns remain temporarily only to support verified backfill and the pre-cutover rollback boundary; new product code does not retain permanent dual-read or dual-write behavior.

Before cutover, a preflight verifies:

- `runtime_providers` is empty or contains only explicitly resolved data;
- every non-null Agent and Agent Runtime Provider string equals the expected configured Kubernetes Provider ID;
- no conflicting Admin registration or bootstrap declaration owns that ID;
- existing Runtime bindings, generations, states, and external Kubernetes resources can be enumerated;
- non-empty legacy per-Runtime Provider configuration is absent or has an explicit conversion plan; and
- the new Kubernetes Provider contract, configuration candidate, enrollment material, and bootstrap declaration are available.

Unexpected Provider rows, multiple logical IDs, ownership conflicts, or unconvertible configuration stop the rollout. Migration does not create anonymous placeholder Providers, silently select another Provider, or infer successful cleanup.

The first Helm bootstrap adapter declares the existing configured Provider ID and reconciles a durable Platform Provider before foreign-key backfill. For the observed deployment this identity remains `system-kubernetes`. The ID is retained as an opaque stable identifier rather than renamed during migration because the Kubernetes Provider writes it to Runtime Pod and PVC labels, selects known resources by that label, and treats a mismatched stable label as requiring replacement. Product terminology, ownership scope, display text, and APIs use Platform Provider; preserving an existing opaque identifier does not preserve the legacy System Provider domain model.

The backfill:

- converts each existing Agent string preference to a validated reference to the bootstrapped Provider;
- converts each existing logical Runtime string binding to an immutable Provider foreign key;
- preserves Runtime, Agent, Workspace, generation, observed-state, Runner-state, and external-resource identity;
- converts the environment-backed Platform default into the instance-wide System Settings Provider reference; and
- records existing incarnation policy application as legacy-unverified until the authenticated Provider resynchronizes a compatible Runtime Policy Snapshot or the incarnation is replaced.

No per-Runtime configuration document is imported for the observed deployment because all three `provider_config` values are empty. Existing controller environment values are classified during Design: deployment infrastructure values remain operator-owned, while product-level values enter the D6 candidate-validation and activation flow rather than becoming silently accepted configuration.

The coordinated cutover is:

1. Pause new Runtime binding and incarnation provisioning while active Runners continue.
2. Apply additive schema migrations and run the fail-closed preflight.
3. Reconcile the stable Bootstrap Declaration and durable Provider.
4. Backfill Agent preferences, logical Runtime Provider foreign keys, and the Platform default.
5. Issue Provider enrollment material through the bootstrap authority and install the Provider-specific credential through the operator-controlled secret path.
6. Deploy the new server and Kubernetes Provider protocol together, removing shared-token-only identity.
7. Authenticate the Provider, validate and accept its Capability Contract, activate required product configuration, and resynchronize existing Runtime resources.
8. Verify that every migrated Runtime remains bound to the same Provider and that all three observed Runtime resources are recovered without implicit replacement before reopening provisioning.

The new server does not accept the shared Runtime Control token as Provider identity and does not fall back to environment-based Provider discovery or default resolution. An old or unenrolled Provider is explicitly disconnected and not ready. Existing Runner incarnations are not replaced solely because of the migration.

After an observation window, contract migrations remove legacy string-only binding writes, `system` ownership-scope semantics, environment-backed default and product-configuration fallback, Helm's direct injection of the server default Provider, Provider self-registration behavior, and shared-token-only Provider authentication. The stable logical ID of an existing Provider is not renamed as part of that terminology cleanup.

Rollback is limited to the pre-cutover boundary. Before new credentials, contracts, configuration revisions, Runtime snapshots, or lifecycle operations become authoritative, additive schema permits a controlled binary and chart rollback. After cutover begins producing new-model state, recovery is roll-forward; the rollout does not restore shared authentication or environment fallback. After contract migrations, old application versions are unsupported.

**Rationale:**

- Actual deployment evidence eliminates the need for a speculative multi-Provider import framework.
- Preserving the existing Provider ID avoids orphaning or replacing running Kubernetes Runtime resources solely for terminology cleanup.
- Fail-closed preflight protects unknown deployments without turning unsupported skeleton data into a permanent compatibility model.
- Coordinated authentication cutover removes the shared-token identity vulnerability instead of carrying it as fallback.

**Rejected alternatives:**

- A generic migration ownership-mapping and adoption subsystem was rejected because the current Provider table is unused and empty in the observed deployment; unexpected data is safer to stop and resolve explicitly.
- Renaming `system-kubernetes` during migration was rejected because Provider-labelled Runtime resources would no longer match discovery and reuse rules and could be orphaned or replaced.
- Long-running dual support for string bindings, environment defaults, shared authentication, and durable Providers was rejected because it would preserve multiple sources of truth and a security bypass.
- A destructive flag-day migration without preflight and Runtime resynchronization was rejected because three active Runtime bindings and their Kubernetes resources must remain observable and controllable.

**Consequences:**

- Migration fixtures must cover the observed empty Provider table with active legacy string bindings and fail on unexpected rows or IDs.
- Helm bootstrap and credential delivery must preserve the configured Provider identity on upgrade.
- E2E evidence must prove existing labelled Runtime resources are resynchronized without replacement and that no shared-token or environment fallback remains after cutover.
- New installations may choose an appropriate stable Provider ID, but Provider IDs are not renamed after they own Runtime infrastructure.
