---
title: "Untrusted Runtime Boundary Requirements"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, security, provider, runner]
document_role: primary
document_type: requirements
snapshot_id: runtime-260811
---

# Untrusted Runtime Boundary Requirements

- Snapshot: `runtime-260811`
- Document reference: `runtime-260811/REQ`

## Problem

The current process-containment feature treats the Runtime Runner as a trusted component that must be protected from Agent-started processes. Its bundled implementation grants elevated workload privileges and depends on node-local security preparation to compensate for that privilege. This trust model does not match the product direction: a future Runtime may use a customer-provided Runner, and the complete Runtime workload must be treated as untrusted by the Azents Platform.

Platform security must therefore remain intact even when the Runner is malicious, compromised, or in possession of its legitimate Runtime credential. Compromise of a Runtime may affect that Runtime and its user-controlled data, but must not grant authority over Azents control-plane resources, Providers, other Runtimes, or platform infrastructure.

## Primary Actor

Platform Administrator.

## Primary Scenario

A Platform Administrator makes a Runtime available whose Runner may be customer-provided or fully compromised. The Runtime connects using its legitimate Runtime-scoped credential and continues to perform ordinary operations inside its own Workspace. Any attempt by that Runtime to select another Runtime identity, acquire Provider or control-plane authority, access unrelated Runtime data, or use workload privileges to affect platform infrastructure is rejected or prevented by boundaries outside the Runtime workload.

## Supporting Scenarios

- Existing Kubernetes and Docker Runtime Profiles without process containment continue to provide ordinary Runtime process, file, Git, transfer, and Workspace behavior.
- A previously stored Infrastructure Profile that requests the removed process-containment feature is not silently reinterpreted as an unrestricted Profile.
- Future optional user filesystem policy may restrict Agent operations to user-authorized Project paths, but that policy protects user-controlled files and is not a platform-security boundary against a malicious Runner.
- Future network restriction may route Runtime HTTP(S) traffic through a separate MITM proxy and prevent direct egress with Provider network policy, independently from filesystem policy.

## Goals

- Treat the complete Runtime workload, including the Runner and Agent-started processes, as untrusted from the Platform perspective.
- Ensure that possession of a valid Runner credential grants authority only for the credential's exact logical Runtime and desired generation.
- Remove the current product-level process-containment feature and its infrastructure prerequisites.
- Restore Runtime workloads to the minimum privilege required for ordinary direct execution.
- Preserve existing unrestricted Agent Workspace and outbound-network behavior in this change.
- Preserve ordinary Runtime operations and lifecycle behavior for supported direct and nested-Docker Profiles.
- Record the superseded trust assumptions, removal rationale, research findings, and independent future filesystem and network directions.

## Non-Goals

- Preventing a compromised Runtime from modifying or destroying its own Workspace or Runtime-local state.
- Protecting user-controlled files from a malicious or compromised customer-provided Runner.
- Implementing optional Project-based filesystem restriction in this snapshot.
- Implementing the MITM proxy or restrictive Runtime egress policy in this snapshot.
- Providing or configuring node-level AppArmor, gVisor, Kata, seccomp profiles, CNI enforcement, firewalls, or Kubernetes cluster security.
- Changing Provider authentication or Provider lifecycle authority.
- Preserving the removed process-containment contract as a legacy or compatibility mode.

## Requirements

### REQ-1. Untrusted Runtime security boundary

Azents must treat every Runtime-originated connection, claim, report, operation result, and transfer message as untrusted input, including input from a Runner holding a valid credential.

**Acceptance criteria**

- A Runner credential resolves exactly one logical Runtime ID and desired generation before registration claims are processed.
- Runner-supplied identity fields cannot select another Runtime, Provider, Workspace, Agent, or Session authority.
- Runtime-originated operation and transfer messages are accepted only for server-created, generation-fenced work belonging to the authenticated Runtime.
- A Runner credential cannot authenticate as a Provider or invoke Provider lifecycle authority.
- Invalid, stale, cross-Runtime, unsolicited, oversized, or malformed Runtime input fails closed without changing unrelated durable state.

### REQ-2. Runtime-local compromise impact

A malicious or compromised Runtime must have no platform authority whose use can affect resources outside that Runtime's intended workload boundary.

**Acceptance criteria**

- Runtime workloads receive no Provider credential, Kubernetes ServiceAccount token, host container-runtime socket, or other general platform-control credential.
- Runtime workloads do not require privileged mode, host namespaces, host paths, node-local security profiles, or elevated capabilities for ordinary direct execution.
- Compromise of the Runner may affect its own processes, Workspace, temporary state, operation results, and availability without granting authority over another Runtime or the Azents control plane.
- Runtime resource consumption and protocol traffic remain bounded so one malicious Runtime cannot create unbounded platform work.

### REQ-3. Remove built-in process containment

The current Provider-owned process-containment capability must no longer be part of the active Runtime Profile, Provider capability, Runner execution, deployment, or product-status contract.

**Acceptance criteria**

- Infrastructure Profile create and replace contracts no longer accept a process-containment module.
- Providers no longer advertise `runtime.process-containment` or accept deployment settings for a containment backend, security profile, or containment RuntimeClass.
- Runner images and startup no longer install, expose, qualify, or invoke the bundled process-containment backend.
- Docker and Kubernetes Runtime workloads no longer add containment-only capabilities, privilege-escalation settings, unconfined seccomp, unmasked proc mounts, AppArmor selection, or containment-only temporary mounts.
- Admin, Workspace, Agent, and Session projections no longer present process-containment status or availability.
- Helm, CI, E2E, fixtures, and documentation no longer require or prepare a node-local containment security profile.

### REQ-4. Preserve ordinary Runtime behavior

Removing process containment must preserve the existing direct Runtime behavior that remains within the untrusted Runtime boundary.

**Acceptance criteria**

- Agent-started processes continue to use the complete Agent Workspace, Runtime temporary storage, ordinary system toolchain, and configured outbound network.
- Process, stdin, file, edit, patch, search, Git/worktree, import, presentation, publication, provider-delivery, and transfer operations retain their existing visible contracts.
- Kubernetes DinD Profiles retain their existing nested-Docker behavior and mutual-exclusion logic no longer references process containment.
- Runtime start, stop, restart, reset, recreate, observation, persistence, and terminal deletion retain their existing semantics.
- Direct Docker and Kubernetes Runtime workloads start without AppArmor preparation or a containment-specific RuntimeClass.

### REQ-5. Fail-closed removal of stored containment configurations

Removal of process containment must not silently convert an existing contained Profile or Runtime configuration into unrestricted direct execution.

**Acceptance criteria**

- A stored Infrastructure Profile or immutable Runtime configuration containing the removed module is rejected as unsupported or unavailable when evaluated under the new product contract.
- No migration deletes the containment field and reuses the resulting Profile as direct execution.
- No Provider drops the unsupported field while applying a lifecycle command.
- Administrators receive a bounded incompatibility result and must explicitly select or create a supported replacement Profile.
- Stop, terminal deletion, and other authority-reducing cleanup remain available where required for an unsupported existing Runtime.

### REQ-6. Independent future policy directions

Future user filesystem policy and Runtime network policy must remain independent capabilities with separate ownership and enforcement claims.

**Acceptance criteria**

- Future Project-based filesystem restriction is described as an optional user-level safeguard against Agent access to unwanted local files, not as protection from a malicious Runner or as a Platform infrastructure boundary.
- Future network restriction is described independently as Runtime egress enforcement through Provider network policy and a separate MITM proxy path.
- Neither future direction is advertised as implemented by this snapshot.
- The current removal does not reserve bwrap, Landlock, AppArmor, gVisor, or another specific implementation as the required future filesystem mechanism.

## Fixed Constraints

- The complete Runtime, including a customer-provided Runner, is outside the Azents Platform trust boundary.
- Runtime compromise is acceptable only within the affected Runtime's processes, data, and availability.
- Platform security must not depend on a Runtime voluntarily following policy.
- Node security, internal-network controls, CNI enforcement, and Kubernetes cluster configuration remain Platform-operator responsibilities.
- There is no silent fallback from a removed or unavailable security claim to a weaker active Runtime configuration.
- Implemented Requirements and accepted ADRs from earlier snapshots remain immutable historical records.

## Open Assumptions

- Existing server-side Runtime credential, generation fencing, operation admission, transfer admission, and resource-limit mechanisms can be retained after a focused malicious-Runner audit.
- Environments with stored process-containment Profiles may require administrator replacement but do not require automatic data migration to a weaker Profile.

## Confirmation

Confirmed by the requester on 2026-08-11 through the direct instruction to document
the research and remove the process-containment implementation without intermediate
approval pauses.
