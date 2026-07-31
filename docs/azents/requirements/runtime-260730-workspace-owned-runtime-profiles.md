---
title: "Workspace-Owned Runtime Profiles Requirements"
created: 2026-07-30
updated: 2026-07-30
implemented: 2026-07-31
tags: [runtime, provider, workspace, infrastructure, security]
document_role: primary
document_type: requirements
snapshot_id: runtime-260730
---

# Workspace-Owned Runtime Profiles Requirements

- Snapshot: `runtime-260730`
- Document reference: `runtime-260730/REQ`

## Problem

Runtime configuration is currently divided across global execution Profiles, Workspace restrictions,
Agent restrictions, and Runtime Provider compatibility. Compute, storage, Docker, and network values
are repeatedly represented as authority ceilings and restrictive overrides. This makes the effective
Runtime difficult for administrators to manage and difficult for Agent users to understand.

The same Profile concept also attempts to represent both customer-facing execution choices and
Provider-owned infrastructure safety constraints. This obscures who owns each setting and makes a
global Profile ambiguous when different Runtime Provider instances operate different infrastructure.

## Primary Actor

Workspace administrator.

## Primary Scenario

A Workspace administrator creates a Runtime Profile owned only by that Workspace. For a
Platform-owned Runtime Provider, the administrator selects one infrastructure Profile offered by
that exact Provider and may add Workspace-owned restrictions that do not weaken the Provider's
infrastructure boundary. An Agent administrator then selects one of the Workspace's Runtime Profiles
as the Agent's complete execution choice without configuring CPU, memory, storage, Docker, or other
per-Agent overrides. The resulting Runtime uses the selected Provider and infrastructure preset with
the Workspace's additional restrictions.

## Supporting Scenarios

- A Platform Kubernetes Runtime Provider publishes Pod Profiles containing safe and stable
  Kubernetes infrastructure presets for customer Workspaces.
- A Platform Docker Runtime Provider publishes Container Profiles containing safe and stable
  container infrastructure presets for customer Workspaces.
- Different Provider instances publish different infrastructure Profiles without creating or
  inheriting a global Profile definition.
- A future Workspace-owned Runtime Provider allows its Workspace to own the corresponding
  infrastructure configuration because the Workspace also owns the infrastructure risk and cost.
- A future permission model controls which users or Agents may select individual Workspace Runtime
  Profiles.
- A Workspace administrator changes additional network policy on a Runtime Profile, and every Agent
  selecting that Profile receives the new desired configuration without an Agent approval step.
- A Platform administrator changes a Provider infrastructure Profile and can recreate every Runtime
  using that Provider so the new infrastructure preset takes effect.
- A Workspace administrator can recreate every Runtime using one Workspace Runtime Profile so its
  current definition takes effect.
- An authenticated Runtime Provider advertises its current capabilities, and valid capability
  changes become authoritative without waiting for System Admin approval.
- A Provider removes a capability required by existing infrastructure Profiles, and the dependent
  configuration remains inspectable while unsupported provisioning is blocked without terminating
  already-running physical Runtimes.
- A Provider adds support for a new compatible infrastructure Profile feature without forcing every
  existing Profile or Provider implementation onto a new Profile contract version.
- A Platform administrator defines an infrastructure Profile using stable Azents configuration
  modules without embedding arbitrary Kubernetes, Docker, or Provider-native configuration.
- Kubernetes Pod Profiles and Docker Container Profiles reuse consistent product semantics where
  appropriate while retaining Provider-kind-specific infrastructure configuration.
- A Platform administrator explicitly defines Kubernetes Runner and optional DinD resource
  requests and limits without inheriting hidden Provider defaults.
- Kubernetes Workspace Volume configuration moves into the new ownership model without changing
  the existing PVC shape or lifecycle behavior.
- Kubernetes Runtime network policy combines an immutable Provider-wide hard boundary, the selected
  Pod Profile policy, and additional Workspace restrictions without allowing a lower scope to
  weaken a higher safety boundary.
- A new Agent receives an explicitly selected or creation-time Workspace default Runtime Profile,
  while an Agent with no available selection remains creatable but cannot provision a Runtime.

## Goals

- Make Runtime Profile a Workspace-owned, non-global execution choice.
- Give Agents only discrete Workspace Runtime Profile selection without per-Agent infrastructure
  overrides.
- Separate Provider-owned infrastructure safety presets from Workspace-owned Runtime choices.
- Align infrastructure configuration authority with the owner of the underlying infrastructure.
- Remove hierarchical compute-resource ceilings and repeated Profile override layers.
- Support Provider-specific infrastructure configuration without pretending it is globally
  portable.
- Make authoritative configuration changes propagate downward without lower-level approval or
  version pinning.
- Allow physical Runtime replacement to be deferred while keeping the newest desired configuration
  authoritative.
- Give each configuration authority an explicit way to recreate every affected Runtime within its
  management scope.
- Treat a valid capability advertisement from an authenticated Provider as current Provider state
  without a separate manual acceptance workflow.

## Non-Goals

- Defining the exact API, database schema, or user-interface layout.
- Defining migration behavior for existing global Profiles or Workspace and Agent restrictions.
- Defining automatic recreation deadlines, compatibility windows, or staged rollout algorithms.
- Implementing the future Runtime Profile selection permission model in this snapshot.
- Defining every Provider-specific Pod Profile or Container Profile field.
- Making infrastructure Profiles portable between different Provider instances or Provider kinds.
- Allowing Agents or lower-level administrators to retain an older parent configuration version.

## Requirements

### REQ-1. Workspace ownership of Runtime Profiles

Every customer-facing Runtime Profile must be owned by exactly one Workspace. Runtime Profiles must
not be global resources, inherited definitions, or Workspace-local overlays of a global Runtime
Profile.

**Acceptance criteria**

- A Runtime Profile belongs to one Workspace and is managed within that Workspace's authority.
- Another Workspace does not automatically receive, inherit, or override the Runtime Profile.
- The product does not require a global customer-facing Runtime Profile definition.
- The Runtime Profile presents one complete execution choice to Agents in its Workspace.

### REQ-2. Discrete Agent Runtime Profile selection

An Agent must select one Workspace Runtime Profile without defining its own infrastructure
restrictions or resource values.

**Acceptance criteria**

- Agent configuration offers only Runtime Profiles owned by its Workspace that the Agent is
  authorized to select.
- Agent configuration does not offer CPU, memory, storage, Docker, network, or similar
  infrastructure override fields.
- An Agent does not create a derived Profile or restriction document from the selected Runtime
  Profile.
- The selected Runtime Profile is sufficient to determine the Agent's intended execution
  environment.

### REQ-3. Provider-scoped infrastructure Profiles

A Platform-owned Runtime Provider must be able to offer infrastructure Profiles owned by that exact
Provider instance. Infrastructure Profiles are Provider resources rather than global product
Profiles.

**Acceptance criteria**

- An infrastructure Profile is identified within one Provider's ownership boundary.
- Infrastructure Profiles from two Provider instances remain distinct even when they have similar
  names or settings.
- A Provider infrastructure Profile cannot be selected through a different Provider instance.
- Removing or disabling a Provider does not cause its infrastructure Profiles to become global or
  silently attach to another Provider.

### REQ-4. Provider-specific infrastructure Profile kinds

Each Runtime Provider kind must represent its infrastructure presets using concepts appropriate to
that infrastructure.

**Acceptance criteria**

- A Kubernetes Runtime Provider can offer Pod Profiles.
- A Docker Runtime Provider can offer Container Profiles.
- A Provider kind may define additional infrastructure Profile kinds when its execution substrate
  requires them.
- Provider-specific infrastructure details are not forced into one misleading globally portable
  resource shape.

### REQ-5. Platform Provider infrastructure safety authority

For Platform-owned Providers, the Provider's infrastructure Profile must define the infrastructure
preset that the Platform is willing to operate for customer Workspaces. Workspace and Agent
configuration must not weaken or replace that preset's Platform-owned safety boundary.

**Acceptance criteria**

- A Kubernetes Pod Profile can govern infrastructure details such as CPU and memory requests and
  limits, Platform-level network policy, attached ServiceAccount, and storage configuration.
- A Docker Container Profile can govern corresponding container resource, network, security, and
  storage configuration.
- Workspace and Agent users cannot replace Platform-owned ServiceAccounts, security settings,
  storage topology, or other Provider-owned infrastructure controls.
- The Platform can refuse Runtime provisioning when the selected infrastructure preset cannot be
  provided safely.

### REQ-6. Workspace Runtime Profile binding

A Workspace Runtime Profile using a Platform-owned Provider must select one exact Provider and one
infrastructure Profile offered by that Provider. Selecting the Workspace Runtime Profile must also
select that Provider path for the Runtime.

**Acceptance criteria**

- The Workspace Runtime Profile identifies one Provider rather than relying on an unrelated Agent
  Provider preference or arbitrary fallback.
- The selected infrastructure Profile belongs to the selected Provider.
- An Agent selecting the Runtime Profile does not separately select a Provider or infrastructure
  Profile.
- Failure of the selected Provider path is explicit and does not silently substitute another
  Provider or infrastructure Profile.

### REQ-7. Workspace-owned additional restrictions

A Workspace Runtime Profile may add Workspace-owned policy, including additional network
restrictions, without weakening the selected Provider infrastructure Profile.

**Acceptance criteria**

- Workspace policy may further restrict network access permitted by the Provider infrastructure
  Profile.
- Workspace policy cannot remove mandatory Provider communication, security, or infrastructure
  boundaries.
- The effective Runtime behavior is explainable as the selected Provider infrastructure preset plus
  the Workspace Runtime Profile's additional restrictions.
- Additional Workspace restrictions do not create a new inherited or derived infrastructure
  Profile.

### REQ-8. Infrastructure authority follows Provider ownership

Infrastructure configuration authority must follow ownership of the Runtime Provider and its
underlying infrastructure.

**Acceptance criteria**

- A Platform-owned Provider keeps Pod, Container, and equivalent infrastructure configuration under
  Platform-owned infrastructure Profiles.
- A future Workspace-owned Provider may allow its Workspace Runtime Profiles to own the applicable
  Pod, Container, resource, network, and storage configuration.
- Platform-owned infrastructure controls do not become Workspace-editable merely because a
  Workspace Runtime Profile references them.
- Provider ownership is visible enough for an authorized administrator to understand who controls
  infrastructure configuration and operational risk.

### REQ-9. No hierarchical resource-ceiling model

Runtime configuration must not depend on merging Platform, Workspace, and Agent compute-resource
ceilings or repeated restrictive override documents.

**Acceptance criteria**

- An Agent does not calculate a narrower CPU, memory, or storage value from its selected Runtime
  Profile.
- A Workspace does not create a resource-ceiling overlay on a Platform infrastructure Profile.
- Provider infrastructure presets express the infrastructure configuration offered by that
  Provider, rather than one layer of a multi-level minimum calculation.
- Runtime selection does not require users to understand governing layers, reductions, or inherited
  resource bounds.

### REQ-10. Future Runtime Profile selection authorization

The Workspace-owned Runtime Profile model must permit a future authorization policy to control who
may select each Profile without changing Profile ownership or reintroducing infrastructure
overrides.

**Acceptance criteria**

- Selection authorization can be associated with a Workspace Runtime Profile.
- Denied users or Agents cannot select the Profile even when they can view other Workspace Runtime
  Profiles.
- Selection authorization does not grant permission to edit Provider-owned infrastructure Profiles.
- Adding the authorization model does not require global Runtime Profiles or Agent-level resource
  overrides.

### REQ-11. Authoritative downward configuration propagation

A configuration owned by a higher authority must propagate to every dependent lower-level
configuration without requiring approval from an Agent or another lower-level component.

**Acceptance criteria**

- A Provider infrastructure Profile change becomes the desired configuration for every dependent
  Workspace Runtime Profile and Agent Runtime.
- A Workspace Runtime Profile change becomes the desired configuration for every Agent selecting
  that Profile.
- Agents and lower-level administrators cannot reject the change, retain the prior parent version,
  or require a separate Apply action.
- Lower-level configuration cannot override a newly changed parent setting.

### REQ-12. Deferred physical Runtime adoption

An authoritative configuration change may wait for physical Runtime recreation before it becomes
effective inside an already-running Runtime.

**Acceptance criteria**

- The newest authoritative configuration is recorded as the Runtime's desired configuration even
  while the current physical Runtime still uses an older applied configuration.
- Deferred adoption is represented as waiting for recreation rather than waiting for lower-level
  approval.
- Starting or recreating the Runtime uses the newest desired configuration.
- A lower-level actor cannot use deferred adoption to permanently pin the Runtime to the older
  configuration.

### REQ-13. Scope-authoritative Runtime recreation

An administrator who owns a configuration scope must be able to trigger recreation of every Runtime
affected by that scope so the current configuration is adopted.

**Acceptance criteria**

- A Platform administrator can trigger recreation of all Runtimes using one Platform Runtime
  Provider or its affected infrastructure Profiles.
- A Workspace administrator can trigger recreation of all Runtimes selecting one Workspace Runtime
  Profile.
- A bulk recreation operation targets only Runtimes within the administrator's authority and the
  selected configuration scope.
- Recreation uses the newest desired Provider infrastructure Profile and Workspace Runtime Profile
  configuration without an Agent Apply action.
- The product reports bounded progress and failures for the affected Runtime set.

### REQ-14. Future rollout-policy extension

The propagation model must permit future policies for compatibility removal, mandatory recreation,
and staged rollout without changing the rule that the newest parent configuration is authoritative.

**Acceptance criteria**

- A future policy can classify an older applied Runtime configuration as temporarily compatible or
  no longer supported.
- A future policy can require recreation by a deadline or rollout stage.
- A future staged rollout can control when physical Runtimes are recreated without giving lower
  levels authority to reject the parent configuration.
- Adding rollout policy does not restore Agent Apply, parent-version pinning, or inherited override
  layers.

### REQ-15. Direct Provider capability advertisement

A valid capability advertisement from an authenticated Runtime Provider must become that Provider's
authoritative current capability state without requiring System Admin review or acceptance.

**Acceptance criteria**

- Provider authentication and identity binding occur before a capability advertisement is accepted.
- Runtime Control automatically rejects structurally invalid, identity-mismatched, or unsupported
  capability advertisements.
- A valid advertisement becomes current Provider state without a candidate, approval, or Apply
  step.
- Provider capability changes propagate to dependent compatibility and desired-configuration
  evaluation without retaining a previously accepted capability version.
- Capability advertisement does not grant the Provider infrastructure authority beyond its
  authenticated Provider ownership and execution boundary.
- Capability revision history may be retained for audit and impact analysis without becoming an
  approval or version-pinning mechanism.

### REQ-16. Capability-loss compatibility handling

When a Provider no longer advertises a capability required by an existing infrastructure Profile,
the current capability state must remain authoritative while dependent configuration references and
already-running physical Runtimes are preserved safely.

**Acceptance criteria**

- The affected infrastructure Profile remains stored and becomes incompatible or blocked rather
  than being deleted or silently rewritten.
- A dependent Workspace Runtime Profile retains its exact Provider and infrastructure Profile
  references but becomes unavailable for new selection and provisioning.
- Existing Agent selections remain attached to the unavailable Workspace Runtime Profile without
  automatic fallback to another Profile or Provider.
- The Runtime desired state reports that current configuration resolution is blocked and does not
  retain the previous capability revision as an authoritative desired input.
- An already-running physical Runtime may continue using its last applied configuration.
- New Runtime creation and operations requiring a new physical Runtime incarnation, including
  start, restart, reset, and recreation, are blocked while required capabilities are unavailable.
- Stop and terminal delete remain available for an affected Runtime.
- Restoring the required Provider capability automatically reevaluates and unblocks the preserved
  Profile references without Admin acceptance or a lower-level Apply action.

### REQ-17. Compatibility-bound Profile contract versioning

Infrastructure Profile contract versions must identify backward-incompatible interpretation
boundaries rather than incrementing for every additive feature.

**Acceptance criteria**

- Adding an optional field, capability, or independently selectable feature module does not require
  a new Profile contract version when existing valid Profiles retain their meaning.
- A contract version changes when an existing valid Profile would become invalid, be interpreted
  differently, or require behavior that was not compatible with the previous contract.
- Field names, value units, default behavior, and security or ownership semantics remain stable
  within one contract version.
- Removed fields or identifiers are not reused with different semantics within the same contract
  family.
- A Provider advertises the compatible contract versions and additive features it supports so an
  unsupported feature produces explicit incompatibility rather than being silently ignored.
- Existing Profiles that do not use a newly added feature remain compatible with Providers that
  support the same contract version but do not advertise that feature.

### REQ-18. Typed infrastructure Profile modules

Provider infrastructure Profiles must use configuration modules with stable Azents-defined
semantics rather than arbitrary substrate-native configuration or unstructured escape hatches.

**Acceptance criteria**

- A Pod Profile does not accept arbitrary PodSpec, Kubernetes YAML, container definitions, volume
  definitions, or security-context fragments.
- A Container Profile does not accept arbitrary Docker create options, daemon arguments, host
  mounts, or equivalent unstructured configuration.
- Each Profile module defines its ownership boundary, required Provider capabilities, supported
  values, omission behavior, compatibility rules, and physical Runtime application impact.
- A Provider explicitly reports incompatibility when it does not support a module or value required
  by an infrastructure Profile.
- New compatible infrastructure features are introduced as additive typed modules or capabilities
  instead of raw configuration fields.
- Typed modules do not expose an escape hatch that bypasses Platform-owned security, storage,
  network, identity, or resource boundaries.

### REQ-19. Shared semantics with Provider-specific realization

Different infrastructure Profile kinds must reuse stable semantic modules for equivalent product
concepts while preserving substrate-specific configuration and Provider-scoped resource identity.

**Acceptance criteria**

- Kubernetes Pod Profiles and Docker Container Profiles remain distinct resource kinds owned by
  their exact Provider instances.
- Equivalent product concepts such as resource allocation, Workspace storage behavior, temporary
  storage, network policy, and Docker execution use consistent semantic definitions where their
  observable meaning is the same.
- Kubernetes-only configuration is represented by Kubernetes modules, and Docker-only
  configuration is represented by Docker modules.
- A Profile may combine shared semantic modules with modules specific to its Provider kind.
- Reusing a semantic module does not make an infrastructure Profile portable, global, inherited, or
  selectable through another Provider.
- A shared semantic module does not erase substrate-specific values required for safe and precise
  infrastructure operation.

### REQ-20. Explicit Kubernetes Pod component resources

A Kubernetes Pod Profile must express CPU and memory requests and limits for known Runtime
components as explicit Platform-owned choices without arbitrary component definitions or hidden
default inheritance.

**Acceptance criteria**

- Every Pod Profile has one typed Runner resource component.
- A Pod Profile using the DinD topology also has one typed Docker engine resource component.
- Each component's CPU request, CPU limit, memory request, and memory limit is represented as either
  an explicit quantity or an explicit choice not to set the corresponding Kubernetes resource
  field.
- Choosing not to set a resource field does not inherit a Provider default, another Profile value,
  or a lower-level override.
- Provider-internal containers, init containers, and control components are not configurable
  through arbitrary Profile resource component names.
- Changing a Pod component resource value requires physical Runtime recreation before it becomes
  applied.
- Ephemeral-storage resources, GPUs, hugepages, extended resources, and device allocation may be
  introduced as additive capability-gated modules without changing the existing contract version.

### REQ-21. Preserve Kubernetes Workspace Volume behavior

The Runtime Profile redesign must preserve the existing Kubernetes Workspace Volume specification
and lifecycle while relocating configuration authority into the new Profile ownership model.

**Acceptance criteria**

- Each logical Kubernetes Runtime continues to use its existing dedicated Workspace PVC model.
- The PVC continues to use the existing storage class, requested capacity, and `ReadWriteOnce`
  access mode behavior without adding new access-mode, volume-mode, or ephemeral-Workspace choices.
- Stop, start, restart, and ordinary Runtime recreation continue to preserve the Workspace PVC.
- Reset continues to delete and recreate the Workspace PVC.
- Terminal deletion continues to delete the Workspace PVC without recreating it.
- The redesign does not silently shrink an existing PVC or introduce a new Workspace Volume
  migration behavior.
- Moving the source of existing storage values into a Provider-owned Pod Profile does not otherwise
  change the generated Kubernetes Volume or PVC semantics.

### REQ-22. Layered Kubernetes network safety boundaries

A Platform Kubernetes Provider must retain a Provider-wide hard network boundary while Pod Profiles
and Workspace Runtime Profiles define successively narrower network policy within their respective
authority.

**Acceptance criteria**

- The Provider-wide hard boundary is owned by the exact Kubernetes Provider and applies to every
  Runtime provisioned by that Provider.
- A Pod Profile defines the Platform network preset offered through that Profile without permitting
  traffic outside the Provider hard boundary.
- A Workspace Runtime Profile may further restrict the selected Pod Profile network policy but
  cannot expand either Platform-owned boundary.
- Effective customer traffic is constrained by all three applicable boundaries rather than by
  replacement or lower-level override.
- Mandatory Runtime Control and other Provider-required communication remains available through a
  separately protected Platform channel that Workspace restrictions cannot remove.
- Changes at any network authority level propagate through desired configuration and require
  physical Runtime recreation when the underlying Kubernetes policy cannot be adopted in place.

### REQ-23. Agent creation-time Runtime Profile selection

A Workspace may define an optional default Runtime Profile that is applied once when an Agent is
created without an explicit Runtime Profile selection.

**Acceptance criteria**

- An explicitly selected Workspace Runtime Profile takes precedence over the Workspace default
  during Agent creation.
- When no Profile is explicitly selected and the Workspace has a default, the Agent stores that
  exact Runtime Profile as its own selection.
- Changing the Workspace default affects future Agent creation and does not move existing Agents to
  another Runtime Profile.
- An Agent may be created when neither an explicit selection nor a Workspace default is available.
- An Agent without a Runtime Profile cannot create, start, or recreate a Runtime until an authorized
  actor selects one of its Workspace's available Runtime Profiles.
- The product does not substitute an arbitrary Runtime Profile, Provider, Platform default, or
  fallback path for a missing Agent selection.

## Fixed Constraints

- Customer-facing Runtime Profiles are owned by Workspaces and are not global.
- Agents select a discrete Workspace Runtime Profile and do not own infrastructure overrides.
- Platform Kubernetes Pod Profiles are scoped to one Platform Kubernetes Runtime Provider instance.
- Platform Docker Container Profiles are scoped to one Platform Docker Runtime Provider instance.
- Platform-owned infrastructure Profiles define non-weakenable Platform infrastructure boundaries.
- A Workspace Runtime Profile using a Platform Provider selects one exact Provider and one of that
  Provider's infrastructure Profiles.
- Workspace-added network policy may only preserve or tighten Provider-owned infrastructure safety
  boundaries.
- Infrastructure configuration authority follows ownership of the Provider and underlying
  infrastructure.
- Runtime provisioning must fail explicitly rather than substitute another Provider or Profile.
- Parent configuration changes are authoritative for all dependent lower-level components.
- No Agent Apply action or lower-level parent-version pinning exists.
- Physical Runtime adoption may be deferred only until recreation.
- Platform and Workspace administrators can trigger recreation across the Runtime scopes governed
  by their configurations.
- Authenticated Providers advertise authoritative current capabilities without System Admin
  acceptance.
- Provider capabilities describe technical compatibility and do not grant additional
  infrastructure authority.
- Capability loss preserves affected Profile and Agent references without fallback, permits
  already-running physical Runtimes to continue, and blocks operations requiring a new Runtime
  incarnation until compatibility is restored.
- Infrastructure Profile contract versions change only at backward-incompatible interpretation
  boundaries; compatible feature additions use capability negotiation within the existing version.
- Infrastructure Profiles contain only typed Azents configuration modules and do not embed raw
  Kubernetes, Docker, or Provider-native configuration.
- Pod and Container Profiles reuse common semantic modules without sharing resource identity or
  hiding Provider-kind-specific infrastructure configuration.
- Kubernetes Pod Profiles explicitly set or intentionally omit Runner and DinD CPU and memory
  requests and limits without Provider-default inheritance.
- Kubernetes Workspace PVC shape and lifecycle remain unchanged while their existing configurable
  values move under the new Profile ownership model.
- Kubernetes network access remains bounded by the Provider-wide hard boundary, the selected Pod
  Profile policy, and any additional Workspace restriction.
- A Workspace default Runtime Profile is applied only at Agent creation, and an Agent without a
  selected Runtime Profile cannot provision a Runtime.

## Open Assumptions

- `Infrastructure Profile` is the umbrella term for Provider-specific concepts such as Pod Profile
  and Container Profile; final user-facing terminology remains a design decision.
- The exact fields and mutation lifecycle of each Provider-specific infrastructure Profile remain to
  be designed.
- The exact status model and user-facing presentation for desired configuration that is waiting for
  Runtime recreation remain to be designed.
- Automatic recreation triggers, maintenance windows, deadlines, rate limits, concurrency, and
  failure recovery remain to be designed.
- Runtime behavior when a referenced Provider infrastructure Profile is disabled or removed remains
  to be designed.
- Migration of existing global Profiles, Workspace restrictions, Agent restrictions, and Provider
  preferences remains to be designed.
- The first version of Workspace-added policy may be limited to network restrictions while the
  selection permission model remains future scope.
- Backward-compatibility classification and staged rollout policy are future extensions to the
  immediate desired-configuration propagation model.

## Confirmation

Confirmed by the requester on 2026-07-30 before ADR and design decisions began.
