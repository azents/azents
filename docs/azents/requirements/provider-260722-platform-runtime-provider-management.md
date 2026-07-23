---
title: "Platform Runtime Provider Management Requirements"
created: 2026-07-22
updated: 2026-07-22
tags: [runtime, provider, admin, platform]
document_role: primary
document_type: requirements
snapshot_id: provider-260722
---

# Platform Runtime Provider Management Requirements

- Snapshot: `provider-260722`
- Document reference: `provider-260722/REQ`

## Problem

An Agent may need a dedicated execution environment even when no Runtime is currently running. Some execution environments are supplied directly by a user, while others must be created automatically in response to an Agent request. Azents needs a product-level concept for the automated provisioning case without making every Runtime depend on a Provider.

The current product does not provide a complete Platform Admin flow for registering, enrolling, configuring, observing, and using an instance-owned Runtime Provider. Trusted deployment bootstrap must also be able to establish the same Provider registration without creating a separate kind of Provider or a second management path. An Azents installation must remain usable when no Platform Provider is installed or connected.

## Primary Actor

Platform Admin

## Primary Scenario

1. A Platform Admin registers a Platform Runtime Provider before its controller is connected.
2. The registration presents the information needed for a Deployment Operator to enroll and run the corresponding Provider controller.
3. The controller connects to the known Provider registration, and the Platform Admin can observe its connection and availability state.
4. The Platform Admin enables the Provider, configures its product-level behavior, and makes it available platform-wide or to selected Workspaces.
5. Before its logical Runtime is created, an authorized Agent editor explicitly selects an eligible Platform Provider or inherits the eligible Platform default.
6. The Agent requests its dedicated Runtime, and Azents binds the new logical Runtime to the resolved Platform Provider.
7. The Provider creates an execution environment containing the common Runtime Runner.
8. The Runner connects as the current physical incarnation of the Agent's logical Runtime.
9. The Provider manages the provisioned environment's lifecycle, while replacement of a Pod, container, VM, or Runner process preserves the logical Runtime identity.
10. The Agent can use the Runtime through the common Runner behavior and diagnostics.

## Supporting Scenarios

- A Deployment Operator uses a trusted bootstrap integration to declare a Platform Provider. Azents creates or reconciles the same kind of known Provider registration used by the Admin flow, after which Admin configuration, connection, matching, and Runtime lifecycle behavior are identical. Helm is the first supported bootstrap adapter.
- A Platform Provider is temporarily disconnected, disabled, unavailable, or out of capacity. Logical Runtimes already bound to it remain bound, and Platform Admins and affected users receive an explicit status instead of Azents silently moving them to another Provider.
- An external Platform Provider becomes permanently unreachable during decommissioning. A Platform Admin can terminate its Azents trust relationship without claiming that external infrastructure cleanup was verified.
- Multiple Platform Providers may coexist with different Workspace availability and Runtime capabilities.
- A Provider replaces a failed or stale physical Runtime incarnation while preserving the Agent's logical Runtime identity and rejecting stale connections.

## Goals

- Define Provider as the automation boundary that provisions and manages execution environments for Agent-dedicated Runtimes.
- Treat every Provider as an external control-plane integration, including a Kubernetes Provider deployed alongside Azents.
- Make Platform Provider registration and product-level management available to Platform Admins.
- Use one Provider resource and lifecycle regardless of whether registration originated from Admin or a trusted bootstrap integration.
- Allow Platform Providers to be offered platform-wide or only to selected Workspaces.
- Keep each logical Runtime bound to one Platform Provider for that logical Runtime's lifetime.
- Deliver an end-to-end Kubernetes Platform Provider as the first concrete Provider implementation.
- Preserve one common logical Runtime and Runner contract across provisioning approaches.
- Keep Azents functional when no Platform Provider is available.
- Establish a foundation that can later support Workspace Providers and user-provisioned Runtimes without redefining the Runtime contract.

## Non-Goals

- Implement user-provisioned Runtime enrollment, pairing, or direct Runner connection from a user's PC, GPU server, VM, or container.
- Implement Workspace Provider registration or management.
- Implement Session-dedicated logical Runtimes; the first delivery remains Agent-dedicated.
- Allow one Runtime or Runner incarnation to serve multiple Agents.
- Move a logical Runtime or its Workspace data between Providers.
- Embed a Provider implementation in the Azents server, worker, or Runtime Control process as a privileged in-process backend.
- Let Platform Admin configuration create or mutate Kubernetes RBAC, RuntimeClass, NetworkPolicy, admission policy, cluster security policy, or other deployment infrastructure.
- Guarantee deletion of external infrastructure that an unreachable Provider can no longer report or control.
- Make the Provider responsible for interpreting Azents Workspace membership or Agent authorization rules.
- Implement additional Provider backends beyond Kubernetes in this delivery.
- Preserve a legacy Provider registration or configuration path as a separate compatibility model.

## Requirements

### REQ-1. Distinguish Runtime provisioning from Runtime execution

Azents must distinguish user-provisioned Runtimes from Provider-provisioned Runtimes. A Provider is required only when an automated component creates and manages the execution environment in response to an authorized Agent request.

**Acceptance criteria**

- A Runtime is not required to have a Provider solely because it uses the common Runner contract.
- A component that directly runs as an Agent's execution environment is treated as a Runtime Runner, while a component that creates Agent-dedicated execution environments is treated as a Provider.
- A Provider operates as a component external to the Azents control-plane processes and uses the common Provider control contract instead of importing or invoking an in-process backend implementation.
- The first delivery implements the Provider-provisioned path without making user-provisioned enrollment part of the required flow.

### REQ-2. Keep one Agent-dedicated logical Runtime

Each Agent must have at most one logical Runtime, and that Runtime must not be shared with another Agent. A physical execution environment is a replaceable incarnation of that logical Runtime.

**Acceptance criteria**

- A Provider provisioning request identifies exactly one Agent and one logical Runtime.
- At most one physical incarnation is accepted as current for the logical Runtime at a time.
- Replacing a Kubernetes Pod or Runner process does not create a second logical Runtime for the Agent.
- Reports and connections from stale incarnations cannot become the current Runtime state.

### REQ-3. Register Platform Providers through Admin

A Platform Admin must be able to create and manage a known Platform Provider registration independently of whether a Provider controller is currently connected.

**Acceptance criteria**

- A Platform Provider appears in Admin management immediately after registration, including before enrollment or connection.
- The registration has a stable identity that controller connections and Agent Runtime assignments can reference.
- Admins can distinguish registered, connected, disconnected, disabled, unavailable, and decommissioned conditions without inferring them from Agent failures.
- Admins can distinguish verified decommissioning from forced retirement with unverified external cleanup.
- A connecting controller cannot create an unknown Platform Provider merely by presenting a new identifier.

### REQ-4. Enroll a controller into a known Platform Provider

A Deployment Operator must be able to connect a Provider controller to the Platform Provider registration created by an Admin without using general Admin credentials.

**Acceptance criteria**

- The Admin flow presents an operator-usable enrollment path for the selected Provider registration.
- Enrollment authority is limited to the intended Provider registration and cannot authorize a different Provider, Agent, Workspace, or general Admin operation.
- Platform Admins can revoke or replace Provider enrollment authority.
- A controller connection is represented separately from the durable Provider registration, so disconnection does not delete the Provider.

### REQ-5. Bootstrap Platform Providers through the same Provider model

A Deployment Operator must be able to establish a Platform Provider registration through a trusted bootstrap integration, and that bootstrap path must use the same Provider registration and management behavior as the primary Admin flow. Helm is the first supported adapter for this capability rather than the product-level registration mechanism.

**Acceptance criteria**

- A bootstrapped Provider appears in the same Admin management surface and is usable through the same connection, configuration, matching, and lifecycle flow as an Admin-registered Provider.
- Repeating the same bootstrap declaration, reconciliation, installation, or upgrade does not create duplicate Provider registrations.
- Bootstrap adapters do not introduce separate static Provider registries or adapter-specific Provider resource types that product consumers must merge.
- Ownership differences between bootstrap-declared and Admin-managed fields are visible and do not silently overwrite Admin-managed product configuration.
- A supported bootstrap adapter can be replaced or supplemented in the future without redefining Provider identity, Admin management, controller connection, matching, or Runtime lifecycle behavior.
- Provider controller connection remains limited to binding to a known Provider and cannot act as an implicit bootstrap path.

### REQ-6. Keep Platform Providers optional

An Azents installation must operate without any registered, enabled, or connected Platform Provider.

**Acceptance criteria**

- Core product areas that do not require a Runtime remain usable when no Provider exists.
- An Agent action that requires provisioning a Runtime receives an explicit unavailable outcome when no eligible Provider can satisfy it.
- Azents does not silently fall back to an unregistered, unauthorized, or deployment-implicit Provider.

### REQ-7. Control Provider availability by Workspace

A Platform Admin must be able to make each Platform Provider available either platform-wide or only to selected Workspaces.

**Acceptance criteria**

- Platform-wide availability makes the Provider eligible for Agents in every Workspace, subject to other Agent and Runtime policy.
- Selected-Workspace availability prevents Agents outside the selected set from being assigned to the Provider.
- Workspace availability changes control new logical Runtime bindings and do not automatically stop, delete, or migrate logical Runtimes that are already bound.
- Existing bindings that are no longer eligible for new selection remain visible to Platform Admins with their affected Workspace and Runtime counts.
- Removing existing use requires an explicit logical Runtime ending and infrastructure cleanup flow with the Provider-declared persistence consequence shown beforehand.
- Workspace membership and Agent authorization are evaluated by Azents before a provisioning request is sent.
- The Provider does not maintain its own independent interpretation of Azents Workspace membership.

### REQ-8. Manage Provider product configuration through Admin

A Platform Admin must be able to view and change supported product-level Provider settings without redeploying the Azents control plane.

**Acceptance criteria**

- The Provider declares typed configurable fields, validation requirements, supported policy scopes, and the application semantics of each setting.
- Admin shows the effective configurable fields, validation results, and expected Runtime impact for the Provider implementation.
- Invalid configuration is rejected before it becomes active.
- Configuration changes have an explicit revision and effective state so Admins can distinguish requested, Provider-accepted, active, and Runtime-applied settings.
- Saving ordinary configuration does not silently restart or replace active Runtime incarnations.
- Deployment infrastructure and cluster security controls remain outside Admin-managed Provider configuration.

### REQ-9. Expose Provider health and provisioning readiness

Platform Admins must be able to determine whether a Platform Provider can currently accept Runtime provisioning requests.

**Acceptance criteria**

- Admin-visible state distinguishes durable registration, controller connection, enabled policy, and provisioning readiness.
- Disconnection or failure is shown without deleting Provider identity or Admin configuration.
- Capacity or capability mismatch produces an explicit non-ready or unsatisfied result rather than an unauthorized fallback.
- Runtime-facing status identifies when progress is blocked by Provider unavailability.

### REQ-10. Match and bind eligible Agent requests

Azents must match a Runtime request only to a Platform Provider that the Agent is authorized to use and that can satisfy the request. Once selected for provisioning, that Provider must remain the logical Runtime's binding for the lifetime of that logical Runtime.

**Acceptance criteria**

- Workspace availability, Provider enabled state, connection readiness, and required Runtime capabilities are considered before provisioning.
- The selected Platform Provider is retained as the logical Runtime's binding across stop, restart, reconnection, and physical incarnation replacement.
- Provider disconnection, temporary unavailability, or capacity exhaustion does not automatically move an already bound logical Runtime to another Provider.
- An existing logical Runtime cannot be reassigned or migrated to a different Provider.
- Using a different Provider requires ending the existing logical Runtime and creating a new logical Runtime through an explicit product lifecycle.
- A provisioning request carries enough Agent and logical Runtime identity for the Provider to create an Agent-dedicated incarnation.
- A Provider cannot claim an unrelated Agent Runtime merely by reporting its identifier.
- Failure to find a match is explicit and does not create a partial Runtime incarnation.

### REQ-11. Require the core Provider lifecycle contract

Every Platform Provider must implement the minimum lifecycle required to create, observe, reconcile, and remove the Runtime incarnations it owns.

**Acceptance criteria**

- The Provider can provision an incarnation for exactly one Agent logical Runtime and start the common Runtime Runner.
- The Provider can observe the infrastructure it owns and resynchronize managed Runtime state after reconnect or Provider restart.
- The Provider can deprovision an incarnation it created and report explicit terminal cleanup success or failure.
- Repeated lifecycle requests converge without creating duplicate current incarnations.
- Provider and Runtime generations prevent stale commands, connections, and reports from becoming current.
- Unsupported optional lifecycle requests receive an explicit unsupported result.
- Deprovisioning a physical incarnation does not by itself delete the Agent's logical Runtime identity.
- Agent decommissioning can require removal of Provider-owned infrastructure and receive an explicit completion or failure result.

### REQ-12. Use the common Runtime Runner contract

Provider-provisioned Runtime incarnations must use the common Runtime Runner behavior rather than a Provider-specific execution interface.

**Acceptance criteria**

- The Kubernetes Provider starts the same supported Runner implementation used by the general Runtime contract.
- Once the Runner is connected, process, file, Git, status, and diagnostic behavior does not depend on whether the environment was created by Kubernetes, another future Provider, or a future user-provisioned flow, except for explicitly declared capabilities.
- Provider connectivity and Runner connectivity remain independently observable.

### REQ-13. Deliver Kubernetes as the first Platform Provider

The first complete Platform Provider implementation must provision Agent-dedicated Kubernetes Runtime Pods and operate through the generic Platform Provider management flow.

**Acceptance criteria**

- A Kubernetes Platform Provider can be registered by Admin and enrolled by an operator.
- The same Kubernetes Platform Provider can be registered through the Helm bootstrap adapter without becoming a different product resource type.
- An eligible Agent request results in a Kubernetes Runtime Pod whose Runner connects as the Agent's current Runtime incarnation.
- Pod replacement and lifecycle operations preserve the logical Runtime contract defined by this snapshot.

### REQ-14. Retire an unreachable external Provider safely

A Platform Admin must be able to end the Azents trust and control relationship with a Provider that cannot complete normal decommissioning, without representing unknown external infrastructure as successfully cleaned up.

**Acceptance criteria**

- Normal decommissioning completes only after every bound Runtime and Provider-owned infrastructure item has the required terminal cleanup evidence.
- Force retire revokes Provider enrollment and connection authority and permanently blocks new matching and provisioning.
- Force retire records external cleanup as unverified rather than successful.
- Logical Runtime bindings, affected Runtime identities, Provider history, and cleanup uncertainty remain visible after force retire.
- Force retire does not automatically reassign affected logical Runtimes to another Provider.
- A later bootstrap declaration or connection attempt cannot silently reactivate the retired Provider.

### REQ-15. Expose Provider-specific Workspace persistence semantics

Each Platform Provider must declare the Workspace persistence behavior it offers, and Azents must preserve that distinction instead of presenting Workspace durability as a universal Runtime guarantee.

**Acceptance criteria**

- A Provider can declare an ephemeral Runtime model in which Workspace data is not preserved across specified lifecycle boundaries.
- A Provider can declare supported persistence behavior across physical incarnation replacement, stop or halt, restart, and deprovisioning.
- Platform Admins and affected Runtime users can determine the effective persistence behavior before performing an action that may discard Workspace data.
- Azents does not claim Workspace preservation when the bound Provider does not support it.
- Azents does not migrate a logical Runtime or its Workspace data to another Provider.

### REQ-16. Declare optional Provider capabilities

A Platform Provider must explicitly declare each lifecycle, persistence, update, cleanup, configuration-scope, capacity, and placement capability that it supports beyond the core Provider contract.

**Acceptance criteria**

- Halt, resume, restart, recreate, reset, Workspace persistence, snapshot or checkpoint behavior, automatic cleanup, automatic replacement, Runtime-scoped configuration, capacity reporting, and placement choices are not assumed to exist.
- A Provider that implements only provision, observe or resynchronize, deprovision, and common Runner bootstrap remains a valid ephemeral Provider.
- Capability declarations distinguish Provider-level behavior from Agent-level overrides and future Session-level overrides.
- Azents does not offer, dispatch, or claim an optional behavior that the bound Provider has not declared.
- Capability changes that affect existing logical Runtimes have an explicit compatibility and application result.

### REQ-17. Resolve capability-aware Runtime lifecycle policy

Azents must resolve Runtime lifecycle settings through a visible hierarchy whose technical limit is the bound Provider's declared capabilities.

**Acceptance criteria**

- Provider capabilities define the maximum set and value range of lifecycle, persistence, update, cleanup, capacity, and placement behavior that can be configured.
- Platform Provider settings define Platform Admin-controlled allowed ranges, restrictions, and default values within the Provider capabilities.
- Agent Runtime settings can override supported values within the Platform limits and otherwise inherit the Platform defaults.
- Removing an Agent override restores the inherited Platform value rather than inventing a new default.
- The first delivery does not implement Session-dedicated Runtimes, but a future Session policy can override the Agent policy within the same Provider and Platform limits.
- The effective value and its source, such as Platform default or Agent override, are visible to an authorized user.
- Values outside Provider capabilities or Platform constraints are rejected rather than silently clamped, ignored, or substituted.
- Unsupported settings and actions are omitted or shown as unavailable with an explicit reason rather than accepted and ignored.
- User-provisioned Runtimes do not receive Provider-managed halt, recreate, cleanup, or forced-update controls merely because they use the common Runner contract.
- Destructive actions show the Provider-declared Workspace persistence consequence before confirmation.

### REQ-18. Coordinate Runtime replacement and configuration adoption

Azents and the bound Provider must coordinate how a Runtime incarnation adopts configuration revisions or is replaced, according to declared Provider capabilities and the effective Runtime lifecycle policy.

**Acceptance criteria**

- A Provider can declare that a setting is immediate, applies to the next incarnation, requires replacement, applies only to a new logical Runtime, or is immutable.
- A user can request Runtime recreation from the product UI when the bound Provider supports user-requested recreation.
- A Provider can report that replacement is recommended or required because of incompatibility, unsupported Runtime state, or configuration revision requirements.
- Automatic stale-Runtime cleanup, idle replacement, or age-based replacement occurs only when the Provider supports it and the effective Runtime policy enables it.
- A required replacement has an observable reason and status; Azents does not present the incompatible incarnation as current and healthy without qualification.
- A required replacement cannot be permanently suppressed by an Agent policy. Platform policy may control safe timing or a deadline, and an incompatible Runtime may block new operations until replacement or external remediation.
- If the Provider does not support recreation, a required replacement becomes an explicit unavailable or externally-remediated condition rather than an unsupported command.
- If an external Provider replaces backend infrastructure autonomously, Azents reconciles the observed incarnation through Runtime generation and state rather than treating it as a different logical Runtime.

### REQ-19. Select the initial Platform Provider predictably

Azents must resolve the Provider for a new logical Runtime through an explicit, visible precedence rather than silently selecting an arbitrary eligible Provider.

**Acceptance criteria**

- A Platform Admin can designate a default Platform Provider.
- Before a logical Runtime exists, an authorized Agent editor can explicitly select one Platform Provider that is available to the Agent's Workspace.
- An explicit eligible Agent selection takes precedence over the eligible Platform default.
- If the Agent has no explicit selection and no eligible Platform default exists, Runtime provisioning is unavailable with an explicit reason.
- The first delivery does not introduce a separate Workspace default Provider.
- Capacity, capability, readiness, Workspace persistence semantics, and supported Agent lifecycle policy are visible before an explicit Provider is selected.
- An explicit selection that is unavailable to the Workspace or cannot satisfy required capabilities is rejected rather than replaced by another Provider.
- Once the logical Runtime is created, the selected Provider becomes the immutable binding described by `provider-260722/REQ-10`.

### REQ-20. Manage Platform Provider administrative lifecycle safely

Azents must own the Platform Provider administrative lifecycle independently of the external Provider controller's connection and implementation.

**Acceptance criteria**

- Disabling a Provider blocks new Provider selection and new incarnation provisioning without automatically stopping an active Runner or deleting an active incarnation.
- A disabled Provider can still receive the cleanup operations required to stop, reset where supported, or deprovision infrastructure it already owns.
- Decommissioning blocks new matching and provisioning and exposes every bound logical Runtime and outstanding infrastructure cleanup dependency.
- Decommissioning does not automatically migrate a logical Runtime, select a replacement Provider, or claim Workspace data portability.
- Verified decommissioning completes only after the required Runtime and infrastructure cleanup evidence is recorded.
- If verified cleanup is impossible because the external Provider is unreachable, `provider-260722/REQ-14` force-retire semantics apply.
- Removing a bootstrap declaration, including one supplied by Helm, does not automatically delete its durable Provider registration, Admin configuration, logical Runtime bindings, or external infrastructure.
- Provider enablement, disablement, decommissioning, forced retirement, controller connection, and provisioning readiness remain independently observable.

## Fixed Constraints

- `Platform Provider` means an Azents-instance-owned Runtime Provider. `Workspace Provider` is reserved for a future Provider owned by one Workspace.
- User-provisioned and Provider-provisioned describe how a Runtime incarnation is created; they are independent of Provider ownership scope.
- A logical Runtime's Provider binding is immutable for that logical Runtime's lifetime. Cross-Provider Runtime reassignment and Workspace migration are outside this capability.
- Workspace persistence is a Provider-declared capability, not a universal property of a logical Runtime. Ephemeral Runtime Providers are valid.
- The mandatory Provider contract is provision, observe or resynchronize, deprovision, and common Runner bootstrap. Other lifecycle, persistence, update, cleanup, capacity, placement, and policy-scope behaviors are optional capabilities.
- Provider-managed lifecycle controls apply only to Provider-provisioned Runtimes. A user-provisioned Runtime cannot be force-managed through a nonexistent Provider.
- Effective Provider-managed Runtime policy resolves through Provider capabilities, Platform Admin defaults and constraints, Agent overrides, and a future optional Session override in that order.
- Initial Provider selection resolves through an explicit eligible Agent selection and then an eligible Platform default. The first delivery has no Workspace default or automatic arbitrary Provider fallback.
- Platform Provider Workspace availability is an admission rule for new logical Runtime bindings. Existing bindings are not destructively changed by an availability edit and require an explicit Runtime ending flow to remove.
- Provider enablement, disablement, decommissioning, and forced retirement are Azents-owned administrative states. An external Provider is required to implement only the per-Runtime core lifecycle and declared optional capabilities.
- Provider controller authentication, Runtime Runner authentication, and any Runtime-scoped control credential are separate authorities and cannot substitute for one another.
- A Provider connection must bind to a known Provider registration; connection is not Provider discovery or creation.
- Trusted Provider bootstrap is an adapter-neutral product capability. Helm is the first adapter, not the domain-level registration mechanism.
- Admin-managed settings cannot grant Kubernetes deployment privileges or mutate cluster security boundaries.
- Every Provider is external to the Azents control-plane processes and communicates through the authenticated Provider control contract. Co-deployment in the same cluster, namespace, Helm release, or repository does not create an in-process exception.
- A Kubernetes Provider deployed and bootstrapped through Helm is a deployment convenience, not a separate built-in Provider type or a weaker identity, authentication, lifecycle, or failure boundary.
- Azents must not report verified Provider infrastructure cleanup without the required Provider evidence. Ending a trust relationship without that evidence is represented as forced retirement with unverified cleanup.
- Runtime or sandbox containers must never receive a mounted host Docker socket as part of this capability.
- A generic unrestricted privileged toggle is not an acceptable Provider configuration boundary.
- Kubernetes runtime isolation mechanisms such as gVisor or RuntimeClass are deployment-operator concerns and are not configured by this feature.
- Git-tracked product behavior and documentation use `Platform Provider`, not the legacy `System Provider` term, for the instance-owned scope.

## Open Assumptions

- Kubernetes is the only concrete Provider backend required for the first delivery, but Provider identity, management, matching, and lifecycle concepts remain backend-neutral.
- The exact list and presentation of Kubernetes product-level settings will be settled in design after the Provider ownership and security boundaries are preserved.
- The exact Workspace persistence capability vocabulary and lifecycle warnings will be settled in design while preserving support for both persistent and ephemeral Providers.
- The exact optional capability identifiers, compatibility rules, and configuration application vocabulary will be settled in design without expanding the mandatory Provider contract.
- Workspace Provider and user-provisioned Runtime flows will be separate future snapshots built on the common logical Runtime and Runner contract.
- A future snapshot may introduce Session-dedicated logical Runtimes. The current delivery implements only Agent-dedicated logical Runtimes and does not define Session Runtime behavior.

## Confirmation

Confirmed by the requester on 2026-07-22. Trusted Provider bootstrapping is a general capability, and Helm is its first supported adapter rather than the product-level registration mechanism.
