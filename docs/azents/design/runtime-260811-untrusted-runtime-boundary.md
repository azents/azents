---
title: "Untrusted Runtime Boundary Design"
created: 2026-08-11
updated: 2026-08-11
tags: [runtime, security, provider, runner, architecture]
document_role: primary
document_type: design
snapshot_id: runtime-260811
---

# Untrusted Runtime Boundary Design

- Snapshot: `runtime-260811`
- Document reference: `runtime-260811/DESIGN`
- Requirements: [Untrusted Runtime Boundary Requirements](../requirements/runtime-260811-untrusted-runtime-boundary.md) (`runtime-260811/REQ`)
- ADR: [Untrusted Runtime Boundary](../adr/runtime-260811-untrusted-runtime-boundary.md) (`runtime-260811/ADR`)

## Current Behavior and Gaps

Profile schema v2 currently accepts a portable `process_containment` module.
Providers advertise `runtime.process-containment`, lower deployment-owned bwrap and
AppArmor settings, and create privilege-expanded Runner workloads. The Runner image
installs set-user-ID bwrap and selects a contained execution backend that projects
filesystem paths and process namespaces around Agent-started commands. Product APIs
and web surfaces expose derived containment status.

This creates four gaps against `runtime-260811/REQ`:

1. the Platform contract treats the Runner as trusted even though future Runners
   may be customer-provided;
2. an untrusted Runtime receives elevated workload privilege;
3. Provider availability depends on node-local AppArmor preparation; and
4. active contracts conflate Platform security with a future user-level file policy.

## Design Overview

The complete Runtime workload becomes one untrusted execution domain. The Platform
retains its existing Runtime-bound credential verifier, generation fencing,
server-created operation admission, transfer admission, resource bounds, and
Provider/Runner authentication separation. It removes the inner process-containment
product feature and restores direct Runner execution under minimum workload
privilege.

Profile schema v2 remains but no longer contains process containment. A narrow
ingress normalizer accepts the old direct serialization containing
`process_containment: null`; a non-null value remains invalid and cannot become
direct execution.

Future Project filesystem policy and MITM-proxy network policy remain documented
directions only.

## Runtime and Control Boundary

Runner authentication continues to derive authority from a signed credential bound
to one logical Runtime ID and desired generation. Registration identity, state
reports, operation events, operation-start claims, transfer identities, and transfer
streams must match that authenticated Runtime and current server-created work.

No Runtime payload is authority for another Runtime, Provider, Workspace, Agent, or
Session. Existing Runtime operation scheduling context remains diagnostic and
fairness metadata rather than authorization proof. Existing queue, payload, deadline,
stream, transfer-size, and concurrency bounds remain the denial-of-service boundary.

The implementation adds or retains focused malicious-Runner tests for cross-Runtime,
stale-generation, unsolicited operation, and transfer attempts. It does not create
a new authentication method or credential lifecycle.

## Profile and API Contract

`RuntimeProcessContainmentModuleV1`,
`RuntimeProfileContainmentStatus`, containment derivation, and capability
classification are removed. Kubernetes and Docker Profile v2 models contain only
their remaining Provider-native fields.

The v2 model ingress normalizer removes an obsolete `process_containment` key only
when its value is `null`. A non-null value is rejected by strict model validation.
This preserves stored direct Profiles without retaining an active containment
option.

Admin inventory represents an invalid stored Profile with bounded incompatibility
evidence instead of failing the complete list. Create and replace requests cannot
submit containment. Public discovery excludes invalid/unavailable Profiles through
the existing compatibility and lifecycle boundaries.

Generated Admin and Public clients are regenerated from the changed OpenAPI
contracts. Admin and customer web surfaces remove containment controls and status.

## Provider Workloads

### Kubernetes

The Provider removes containment bootstrap settings, RuntimeClass validation,
RuntimeClass RBAC, AppArmor selection, host user-namespace selection used only by
containment, containment-specific volumes, and containment-specific security
contexts.

The ordinary Runner container remains UID/GID 1000, non-root, with privilege
escalation disabled, every capability dropped, `RuntimeDefault` seccomp, default
proc masking, and no ServiceAccount token. DinD retains its distinct privileged
engine container contract and does not grant that authority to the Runner.

### Docker

The Provider removes AppArmor preflight, containment environment settings,
containment capability advertisement, containment security options, user-namespace
mode, unmasked paths, and containment-specific temporary mounts.

The ordinary Runner container remains UID/GID 1000, drops all capabilities, enables
Docker no-new-privileges behavior, and relies on the daemon's default seccomp and
masked-path policy. DinD and other Provider-native behavior remain unchanged.

## Runner

Runner selects direct execution unconditionally. The containment bootstrap parser,
bwrap execution backend, launcher, qualification probes, child seccomp compiler,
private containment paths, and contained environment builder are removed.

The Runner image no longer installs bubblewrap or creates a set-user-ID executable.
Direct process environment, process lifecycle, deadlines, cancellation, output
buffering, typed file operations, Git, imports, presentation, and transfer behavior
remain unchanged.

The common filesystem access-policy abstraction is removed where it exists only to
maintain bwrap/Python parity. Relative paths continue to resolve from the Agent
Workspace, while absolute paths and native I/O use the Runtime operating-system
user's ordinary filesystem permissions. Operation-specific kind and mutation safety
remains without claiming Project-based restriction or infrastructure isolation.

## Deployment and Operations

Helm removes process-containment values, environment variables, RuntimeClass RBAC,
and documentation. Provider startup no longer checks AppArmor or reports
containment availability. Existing direct Provider registration becomes independent
from node-local AppArmor support.

The containment-specific Docker and Kubernetes E2E lanes, AppArmor load/unload
steps, conformance probes, fixtures, and CI path routing are removed. Remaining
deterministic Runtime lifecycle and operation E2E coverage becomes authoritative.

No live cluster change or AppArmor profile unload is part of the code delivery.
Operators may remove obsolete node-local profiles independently after upgrading.

## Stored Configuration and Rollout

No database migration rewrites a non-null containment claim. Existing mutable
Infrastructure Profiles with the obsolete null key remain readable as direct
Profiles. Existing Profiles with an enabled claim become invalid/unavailable and
must be explicitly replaced by an administrator.

Immutable resolved Runtime revisions containing enabled containment remain
historical evidence. New Provider versions reject them for creation or replacement.
The existing authority-reducing stop and terminal-delete paths remain available
without treating the old claim as an active direct configuration.

Rollback to a version that still implements containment may read its historical
Profiles again. Forward rollout never silently weakens them.

## Observability

Containment availability, backend, qualification, and AppArmor reason metadata are
removed. Existing Runtime authentication, registration, operation, transfer,
generation, queue-pressure, and lifecycle diagnostics remain.

Invalid stored Profile projections use the existing bounded
`profile_document_invalid` compatibility reason. No logs include raw Profile
documents, credentials, commands, file content, or transfer payloads.

## Future Directions

### Optional user filesystem policy

A future snapshot may add an unrestricted/restricted user policy over registered
Project paths. A conforming Runner may compile it with Landlock, bwrap, mount
projection, or another backend and must apply equivalent rules to typed operations.
The feature protects user local files from Agent actions; it does not protect the
Platform from a malicious Runner.

### MITM proxy network policy

A future snapshot may deploy a separate MITM proxy workload, allow Runtime egress
only to that proxy plus mandatory Platform destinations, and inject HTTP(S) proxy
and CA settings into the Agent environment. Provider network policy is the
anti-bypass mechanism. This direction is independent from filesystem policy.

## Test Strategy

### E2E primary matrix

- Docker direct Runtime lifecycle, process, file, Git, transfer, persistence, reset,
  and terminal deletion without AppArmor preparation.
- Kubernetes direct Runtime lifecycle and operation journey with minimum Runner
  security context and no containment RuntimeClass or Localhost AppArmor profile.
- Kubernetes DinD journey retaining its existing privileged engine boundary.
- Existing stored contained Profile fixture resolving to bounded unavailable
  evidence without direct execution.

### Focused verification

- Core Profile parsing accepts old null serialization and rejects enabled
  containment.
- Provider capability contracts omit `runtime.process-containment`.
- Docker and Kubernetes workload manifests contain no containment-only privilege,
  mount, environment, RuntimeClass, or AppArmor fields.
- Runner direct execution and operation tests pass after backend removal.
- Admin/public OpenAPI and generated clients contain no containment contracts.
- Repository-wide absence checks find no active bwrap, AppArmor profile, containment
  environment, capability, UI, or CI references outside immutable historical
  Requirements, ADRs, and Designs.

E2E prerequisites no longer include AppArmor. Missing ordinary Docker or Kubernetes
test infrastructure follows the existing required-lane failure policy rather than a
containment-specific skip.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Runtime credential and protocol authority remain exact-Runtime and generation scoped while all Runtime input is untrusted | `runtime-260811/REQ-1`, `REQ-2`; `runtime-260811/ADR-D1` | `required` |
| M2 | Remove the active process-containment Profile, capability, status, Provider, Runner, UI, and deployment contract | `runtime-260811/REQ-3`; `runtime-260811/ADR-D2` | `required` |
| M3 | Preserve direct v2 documents with a null-key normalizer and reject enabled stored containment without downgrade | `runtime-260811/REQ-5`; `runtime-260811/ADR-D3` | `decided` |
| M4 | Restore minimum-privilege direct Docker and Kubernetes Runner workloads | `runtime-260811/REQ-2`, `REQ-4`; `runtime-260811/ADR-D4` | `required` |
| M5 | Preserve ordinary direct and DinD Runtime behavior | `runtime-260811/REQ-4`; current Runtime Control and persistence Specs | `existing` |
| M6 | Record optional user filesystem policy as an independent future capability without selecting a backend | `runtime-260811/REQ-6`; `runtime-260811/ADR-D5` | `decided` |
| M7 | Record MITM proxy plus Provider network policy as an independent future network direction | `runtime-260811/REQ-6`; `runtime-260811/ADR-D6` | `decided` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Profile process-containment module, capability, compatibility and status | M2 | Direct Profile v1/v2 and DinD M5 | Core models, APIs, OpenAPI, clients, web | Active-code grep and generated-schema checks |
| bwrap Runner backend, launcher, qualification and child seccomp | M2 | Direct execution M5 | Runner source, tests and image | No installed binary, backend selection or source reference |
| set-user-ID bwrap and containment workload privilege | M2, M4 | Minimum-privilege workload M4 | Docker/Kubernetes Providers and manifests | Manifest/security-context tests |
| Localhost AppArmor profile and preflight | M2, M4 | Operator-owned node security | Docker Provider image, Helm, CI and E2E | No shipped profile or preparation step |
| Containment RuntimeClass and RBAC | M2, M4 | Operator-owned runtime selection | Kubernetes Provider settings and Helm | Rendered manifest absence |
| Containment-specific temporary/private mounts and environment | M2 | Ordinary Workspace and Runtime temporary behavior M5 | Providers and Runner | Provider and operation tests |
| Containment UI controls and status | M2 | Ordinary Profile and Runtime status | Admin/customer web and clients | Typecheck and UI tests |
| Containment-specific E2E lane and fixtures | M2 | Direct Runtime E2E matrix | CI and testenv | Workflow and fixture absence |
| Earlier implemented snapshot documents | `runtime-260811/REQ` fixed constraint | Immutable historical records | None; retained | Documents remain unchanged |

## Feasibility

- M1: feasible; current authentication, message identity, operation admission, and
  transfer fencing already implement the core boundary and need focused malicious
  Runner regression coverage.
- M2: feasible; active references are repository-local and have no external
  persistence table dedicated to containment.
- M3: feasible; strict Profile ingress can normalize only the obsolete null key and
  reject non-null values. Admin invalid-document projection needs a nullable typed
  spec instead of reparsing unconditionally.
- M4: feasible; direct Provider paths already exist and require privilege reduction,
  not a replacement runtime.
- M5: feasible; direct and DinD paths are existing supported behavior.
- M6 and M7: documentation-only future directions in this snapshot.

No implementation blocker remains.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: 2026-08-11
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`
- Approved scope: The requester directly instructed the agent to document the research and future directions, remove the complete bwrap/AppArmor process-containment implementation, and create the PR without intermediate approval waits.
