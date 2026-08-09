---
title: "Provider-Owned Runtime Process Containment Requirements"
created: 2026-08-08
updated: 2026-08-08
tags: [runtime, provider, security, sandbox, containers]
document_role: primary
document_type: requirements
snapshot_id: runtime-260808
---

# Provider-Owned Runtime Process Containment Requirements

- Snapshot: `runtime-260808`
- Document reference: `runtime-260808/REQ`

## Problem

An Agent Runtime currently gives agent-started processes the operating-system view and authority of the Runner container. A prompt injection, malicious Skill, unsafe command, or incorrect model decision can therefore expose trusted Runner state and other Runtime infrastructure surfaces that are not part of the Agent Workspace. Platform Administrators need a Provider-owned containment option that limits the effect of a fully compromised agent process without removing the development tools, Agent Workspace behavior, or ordinary outbound connectivity that make the Runtime useful.

## Primary Actor

Platform Administrator.

## Primary Scenario

A Platform Administrator publishes a Provider Infrastructure Profile with required process containment. A Runtime created from that Profile preserves normal Agent Workspace work, system development tools, temporary work, and outbound internet access, while agent-started processes cannot acquire infrastructure authority or access trusted Runner, Provider, host, or unrelated Runtime resources. The Provider verifies that it can enforce the required boundary before reporting the Runtime ready and does not silently create a weaker Runtime when containment is unavailable.

## Supporting Scenarios

- The Kubernetes Runtime Provider offers a contained Infrastructure Profile suitable for production use within its Provider network boundary.
- The Docker Runtime Provider offers the same filesystem, process, privilege, credential, and socket containment for development use, while retaining its Provider-specific network assurance.
- A Platform Administrator publishes a separate nested-container development Profile when agents need Docker-compatible container execution.
- A future feature adds user-configurable restrictions within the Agent-controlled Runtime area without weakening the Provider-owned infrastructure boundary.

## Goals

- Contain the effect of a fully compromised agent-started process within the Agent-controlled Runtime area.
- Protect trusted Runner, Runtime Control, Provider, host, and unrelated Runtime authority from agent-started processes.
- Preserve existing Agent Workspace, Session, Project, Skill, instruction-file, and shared-file behavior in the initial feature.
- Preserve ordinary development tooling, temporary-file workflows, and outbound internet usage.
- Let Platform Administrators provide the capability through Provider Infrastructure Profiles.
- Support both Kubernetes and Docker Runtime Providers in the initial feature.
- Keep the product-level capability portable to future non-Linux Runtime Providers.
- Preserve a restriction-only extension point for a future user-configurable behavior-control layer.
- Keep Session input handling and model execution independent from Runtime startup, qualification, and Runner readiness latency.

## Non-Goals

- Preventing prompt injection or model jailbreak at the inference layer.
- Restricting access between Sessions inside the same Agent Workspace.
- Changing Project registration into a read or write authorization boundary.
- Restricting unregistered Project discovery or access inside the Agent Workspace.
- Preventing Agent-controlled persistence inside the Agent Workspace.
- Adding Workspace, Agent, Session, or user overrides in the initial feature.
- Adding domain allowlists, domain denylists, mandatory proxy routing, or MITM inspection in the initial feature.
- Providing process containment and nested Docker execution in the same Infrastructure Profile.
- Claiming Kubernetes-equivalent network assurance for the development-oriented Docker Runtime Provider.

## Requirements

### REQ-1. Provider-owned containment profiles

Platform Administrators must be able to publish Provider Infrastructure Profiles that require process containment as a complete Provider-owned Runtime capability.

**Acceptance criteria**

- Containment configuration is owned by the Runtime Provider Infrastructure Profile.
- Workspace and Agent configuration can select a Runtime Profile backed by the Infrastructure Profile but cannot modify or weaken its containment settings in the initial feature.
- The product distinguishes a contained Profile from a Profile that does not provide containment.
- Raw operating-system sandbox configuration is not accepted from Workspace, Agent, Session, or end-user surfaces.

### REQ-2. Compromised-process infrastructure boundary

The containment boundary must assume that an agent-started process is fully controlled by an attacker and prevent that process from acquiring trusted Runtime infrastructure authority.

**Acceptance criteria**

- Agent-started processes receive no Runner, Runtime Control, or Provider authentication secret.
- Agent-started processes cannot observe, signal, or control trusted Runner processes through the Runtime process view.
- Agent-started processes cannot access Provider credentials, Kubernetes workload credentials, host container-runtime authority, or unrelated Runtime storage.
- Agent-started processes cannot use an unapproved local daemon or infrastructure socket to gain authority outside the contained process boundary.
- Successful containment does not rely on the model following instructions or voluntarily avoiding protected resources.

### REQ-3. Stable non-root process identity

Contained agent processes must retain the Runtime's ordinary non-root identity and must not receive synthetic root authority.

**Acceptance criteria**

- Agent-started processes observe UID and GID 1000 across the bundled Kubernetes and Docker Providers.
- Agent-started processes receive no effective, permitted, inheritable, ambient, or bounding capability.
- Privilege escalation and set-user-ID or set-group-ID elevation are unavailable.
- Agent-started processes cannot create an additional user namespace to obtain a synthetic root identity.
- Agent Workspace ownership and ordinary file creation remain compatible with the existing UID and GID.

### REQ-4. Agent Workspace behavior preservation

The initial containment feature must preserve the Agent Workspace as the Agent-controlled filesystem area rather than introduce Session or Project authorization within it.

**Acceptance criteria**

- Existing access to the Agent Workspace root, Session working folders, registered Projects, unregistered Project directories, Agent-level instructions, Skills, and shared files remains available to agent-started processes.
- Existing read and write behavior inside the Agent Workspace is not reduced merely because process containment is enabled.
- Other Session working folders inside the same Agent Workspace are not hidden by the initial containment feature.
- Future user-configurable restrictions may narrow this area without changing the Provider-owned infrastructure boundary.

### REQ-5. Useful system and development environment

Contained agent processes must retain the system and development environment needed for ordinary Agent work while being unable to modify trusted Runtime system state.

**Acceptance criteria**

- Existing bundled command-line tools, language runtimes, compilers, package clients, Git tooling, and browser dependencies remain usable when their normal operation does not require nested containers or trusted infrastructure authority.
- Agent processes can read and execute the Runtime's ordinary system toolchain.
- Agent processes cannot persistently modify the Runtime image's system files or trusted Runner installation.
- Trusted Runner code, private Runtime state, credentials, and infrastructure sockets are unavailable even when adjacent system files remain readable.

### REQ-6. Runtime-scoped Agent temporary storage

Contained agent processes must have dedicated Runtime-scoped temporary storage suitable for ordinary development, imports, and multi-operation workflows.

**Acceptance criteria**

- Agent-started processes and Agent-authorized native file or import operations observe the same temporary files during one physical Runtime lifetime.
- The Agent temporary area is presented through the Runtime's standard temporary path and supports existing `/tmp/agent` workflows.
- Trusted Runner temporary state is separate and unavailable to agent-started processes.
- Agent temporary storage is not checkpointed or treated as durable Agent Workspace state.
- Preservation is not guaranteed across physical Runtime replacement, reset, or terminal deletion.
- The initial feature does not divide temporary storage by Session.

### REQ-7. Ordinary outbound connectivity

Contained Profiles must remain useful for network-dependent development and daily operations.

**Acceptance criteria**

- Git network operations, package downloads, web requests, and ordinary external API access can function within the Provider's effective network boundary.
- Containment does not broaden the egress already allowed by the Provider and selected Profile.
- Kubernetes and Docker Providers may provide different network assurance while satisfying their declared Profile contract.
- Trusted Runtime endpoints may remain reachable within the Provider network, but agent-started processes receive no endpoint configuration, authentication credential, or execution authority for them.
- The initial containment claim does not imply network-level invisibility of Runtime Control or other authenticated services.
- Domain-specific policy, mandatory proxy routing, and direct-egress removal remain outside the initial feature.

### REQ-8. Mutual exclusion with nested-container authority

A single Infrastructure Profile must not combine process containment with Agent-accessible nested Docker execution.

**Acceptance criteria**

- A Profile that requires process containment cannot enable the nested Docker capability.
- A Profile that enables nested Docker execution cannot claim or enable this process-containment capability.
- Profile validation rejects the conflicting combination before Runtime creation.
- Runtime preparation verifies the absence of Agent-accessible Docker daemon authority before reporting a contained Runtime ready.
- Platform Administrators can publish separate contained and nested-container development Profiles.

### REQ-9. Multi-Provider initial availability

Both bundled Linux Runtime Providers must be able to offer contained Infrastructure Profiles in the initial feature.

**Acceptance criteria**

- The Kubernetes Runtime Provider can advertise, validate, create, and observe a contained Profile.
- The Docker Runtime Provider can advertise, validate, create, and observe a contained Profile for development use.
- Provider-specific differences in network enforcement are reported honestly and do not weaken filesystem, process, privilege, credential, or socket containment claims.
- A Provider that cannot enforce the required local containment does not advertise the Profile as available.

### REQ-10. Fail-closed qualification and readiness

A contained Runtime must become ready only after its Provider and Runner have verified that the required containment boundary is enforceable in the actual environment.

**Acceptance criteria**

- Qualification covers the effective operating-system, container-runtime, kernel, and mandatory-access-control environment rather than relying only on declared support.
- A qualification or startup failure prevents the Runtime from being reported ready under the contained Profile.
- Failure does not silently remove containment, switch to nested Docker, or select another Infrastructure Profile.
- Operators receive a bounded diagnostic that identifies the unsupported or failed containment category without exposing secrets.

### REQ-11. Portable product contract

The product-level containment contract must describe observable security guarantees rather than one operating-system implementation.

**Acceptance criteria**

- Public and administrative product concepts do not require Linux-specific sandbox terminology.
- Provider capability evidence can identify its concrete backend for diagnostics and qualification.
- A future macOS Runtime Provider can satisfy the same product capability through a different implementation.
- Windows remains a lower-priority future target and does not block the initial Linux implementation.

### REQ-12. Future restrictive policy composition

The initial Provider-owned boundary must leave room for a later user-configurable layer that only narrows Agent behavior.

**Acceptance criteria**

- The initial feature provides no Workspace, Agent, Session, or user containment override.
- A future policy can narrow filesystem, network, socket, or capability access without widening the Provider Profile.
- Future domain restrictions and proxy enforcement can compose with the Provider boundary without redefining its ownership.
- The initial design does not require nested operating-system sandboxes as the only way to add the later restrictive layer.

### REQ-13. Explicit opt-in rollout and recreation

The initial process-containment rollout must preserve existing Profiles and Runtimes and require explicit adoption through a separate contained Infrastructure Profile.

**Acceptance criteria**

- Existing Infrastructure Profiles and their active Runtimes do not gain containment automatically during the initial rollout.
- A Platform Administrator can publish a separate contained Infrastructure Profile without replacing an existing compatibility or nested-container Profile.
- Adopting or leaving a contained Profile requires physical Runtime recreation and preserves durable Agent Workspace state.
- The product does not report an existing non-contained Runtime as contained before the replacement Runtime has qualified and become ready.
- Rollback selects a non-contained Profile explicitly and also requires physical Runtime recreation.
- Changing the bundled default to a contained Profile remains a future rollout decision after implementation maturity and qualification evidence improve.

### REQ-14. Complete Agent-originated operation coverage

Every Agent-originated process and Agent-facing filesystem or transfer operation must observe the same Provider-owned containment boundary.

**Acceptance criteria**

- Foreground, long-running, background, and descendant processes started for an Agent run within the contained process authority.
- Agent-facing native read, write, delete, search, edit, patch, import, presentation, and transfer operations cannot access a path hidden from the contained Agent authority.
- Native Runner implementation does not become a bypass merely because an operation is executed by the trusted Runner process instead of a sandboxed child process.
- Product-owned typed system operations may use separately validated authority only for their fixed operation and exact trusted identity and path scope.
- An Agent cannot convert a typed system operation into arbitrary command execution or arbitrary filesystem authority.
- Verification covers both process tools and native operation tools rather than treating successful shell isolation as complete containment evidence.

### REQ-15. Layered containment visibility

Containment state and constraints must be visible at the level needed by each actor without exposing sensitive infrastructure detail.

**Acceptance criteria**

- Platform Administrators can inspect Profile configuration, Provider compatibility, qualification state, recreation impact, and bounded backend diagnostics.
- Workspace and Agent users can see whether effective process containment is enabled, whether nested Docker is available, whether recreation is required, and a safe bounded reason when the selected Profile is unavailable.
- The Agent model receives behaviorally relevant constraints, including writable Agent Workspace access, temporary storage availability, read-only Runtime system state, non-root execution, nested-Docker unavailability, and ordinary outbound connectivity.
- The Agent model's behavioral summary is derived from the resolved desired Runtime Profile and describes the contract that Runtime operations will follow when they are available.
- The behavioral summary does not claim that a physical Runtime is currently ready, connected, qualified, or actively enforcing the Profile.
- Trusted Azents components render typed Profile values through code-owned bounded templates; Profile-authored arbitrary prompt text, Runner free-form diagnostics, and Runner-provided prompt text do not enter model context.
- Provider and Runner configuration evidence validates physical application and readiness but is not directly rendered or translated into model prompt wording.
- Runtime readiness, connection state, and qualification evidence do not participate in prompt construction.
- When the resolved desired Profile is blocked or unavailable, the Agent model receives only a generic statement that Runtime-dependent operations are unavailable, without Provider, qualification, or internal diagnostic detail.
- Runtime-dependent actions and tools execute only through a Runtime configuration matching the resolved desired Profile contract presented to the model.
- Model context and user-facing summaries do not expose raw sandbox arguments, mandatory-access-control rules, credential locations, Runtime Control endpoints, or sensitive internal path inventories.
- Audit and operational evidence records Profile mutation, adoption, rollback, recreation, and qualification outcomes without secret values.

### REQ-16. Runner-independent Session execution

Agent Session execution must not impose a hidden Runtime-readiness prerequisite on an otherwise model-eligible turn, while explicit Runtime-dependent actions and tool calls must be able to wait for the Runtime they require.

**Acceptance criteria**

- Human input admission, Session wake-up, Agent Run ownership, and prompt assembly do not wait for Runtime creation, startup, qualification, registration, heartbeat, reconnection, or readiness.
- An otherwise model-eligible turn is not delayed solely for background Runtime readiness when no ordered Runtime-dependent action is awaiting execution.
- Prompt assembly performs no synchronous Runner request or readiness polling and uses only an immediately available validated resolved-Profile snapshot.
- Missing Runner state or qualification evidence does not delay or prevent otherwise valid model execution and does not alter the Profile-derived behavioral contract in the prompt.
- A blocked or unavailable resolved Profile changes the Runtime fragment to a bounded unavailable statement but does not prevent otherwise valid model execution.
- Runtime creation, startup, recreation, qualification, and evidence convergence proceed independently from Session model execution.
- An ordered Runtime-dependent action, including working-folder or worktree materialization, waits for Runner readiness and then awaits its own bounded Runner operation before subsequent ordered Session work proceeds.
- A model-requested Runtime tool call waits for Runner readiness and then awaits its own bounded Runner operation before returning its result to the model.
- Runtime-dependent actions and tools wait for a Runtime whose applied configuration matches the resolved desired Profile contract rather than accepting an earlier or different ready Runtime.
- Runtime-readiness waiting for an explicit action or tool call is bounded, cancellable, and attributable to that visible operation rather than represented as hidden Session startup latency.
- Existing Session and Agent behavior that does not require a Runtime operation remains available while the physical Runtime is unavailable.

## Fixed Constraints

- The Platform Administrator and Runtime Provider own the initial containment policy.
- The initial feature focuses on Provider infrastructure containment, not Session isolation or user behavior policy.
- The Agent Workspace remains the Agent-controlled area with its existing access behavior.
- Normal outbound internet access remains available.
- Kubernetes and Docker Runtime Providers are both initial targets.
- The Docker Runtime Provider is development-oriented and may expose weaker network assurance than Kubernetes.
- Nested Docker authority and process containment are mutually exclusive within one Infrastructure Profile.
- The concrete Linux implementation must not become the cross-platform product contract.
- Unsupported or failed containment is fail-closed.
- The initial rollout is opt-in through separate contained Infrastructure Profiles and does not migrate existing Runtimes automatically.
- Model-visible containment behavior is derived from the resolved desired Runtime Profile through code-owned templates and is independent from Runner readiness or evidence.
- Runner readiness is not a prerequisite for Session prompt construction or an otherwise eligible model dispatch, except when an explicitly ordered Runtime-dependent action must complete first.

## Open Assumptions

- The exact Provider-visible containment assurance fields are a design decision after Requirements confirmation.
- The exact contained Profile naming and presentation are design decisions.
- Future user-configurable filesystem and domain restrictions will be defined by a separate Requirements snapshot after the Provider-owned boundary is stable.
- A later snapshot may make containment the bundled default for new Profiles after compatibility, operational maturity, and qualification evidence are sufficient.

## Confirmation

Confirmed by the requester on 2026-08-08 before ADR and design decisions began.
