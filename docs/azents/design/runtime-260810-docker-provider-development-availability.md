---
title: "Docker Runtime Provider Development Availability Design"
created: 2026-08-10
updated: 2026-08-10
tags: [runtime, provider, docker, development, testenv, security]
document_role: primary
document_type: design
snapshot_id: runtime-260810
---

# Docker Runtime Provider Development Availability Design

- Snapshot: `runtime-260810`
- Document reference: `runtime-260810/DESIGN`
- Requirements: [Docker Runtime Provider Development Availability Requirements](../requirements/runtime-260810-docker-provider-development-availability.md) (`runtime-260810/REQ`)
- ADR: [Docker Runtime Provider Development Availability](../adr/runtime-260810-docker-provider-development-availability.md) (`runtime-260810/ADR`)
- Mode: Collaborative
- Decision owner: requester

## Current Behavior and Gaps

Docker Provider settings distinguish direct deployment from configured bwrap
containment. When containment is configured, Provider startup validates Docker daemon
AppArmor evidence and terminates before registration when the evidence is absent.

The shared E2E Provider fixture always configures bwrap, always publishes a contained
Docker Infrastructure Profile, and therefore makes AppArmor a prerequisite for
deterministic, Runtime Provider, and Web Surface E2E alike. This prevents local
development E2E from entering unrelated product journeys on Docker hosts without
AppArmor.

## Requirement and ADR Traceability

| Requirement | Design mechanisms |
| --- | --- |
| `runtime-260810/REQ-1` | Effective Provider containment resolution and retained direct registration |
| `runtime-260810/REQ-2` | Capability advertisement derived from effective containment support |
| `runtime-260810/REQ-3` | Existing Profile compatibility rejection with no lifecycle downgrade |
| `runtime-260810/REQ-4` | Lane-level direct/contained fixture policy and CI prerequisite split |

## Architecture and Ownership

Trusted Docker Provider deployment settings remain the requested containment
configuration. Before building the Provider lifecycle object and registration,
startup resolves an effective containment configuration:

- no configured backend: direct support;
- configured backend plus Docker AppArmor evidence: direct and contained support;
- configured backend without Docker AppArmor evidence: direct support with one bounded
  warning.

The effective configuration is supplied consistently to both the lifecycle provider
and its current capability advertisement. Runtime Control and existing Profile
compatibility remain authoritative for whether a contained Infrastructure Profile can
be selected.

No database state, API field, configuration schema, or new capability is introduced.

## Runtime and Failure Behavior

Missing Docker AppArmor support no longer escapes startup as an exception. The
Provider logs one content-free warning category and registers its direct contract.
Other invalid deployment settings, unsupported backend names, malformed timeouts, and
authentication or Control failures retain their existing failure behavior.

Contained Runtime lifecycle commands cannot reach a Provider advertisement that lacks
the required schema and capability. There is no command-time downgrade or direct
fallback.

## E2E Fixture and CI Policy

One trusted environment switch controls the shared E2E Docker Provider fixture:

- unset or false: omit containment deployment settings and publish schema-v1 direct
  Infrastructure Profile;
- true: configure the existing bwrap/AppArmor deployment and publish schema-v2
  contained Infrastructure Profile.

Deterministic and Web Surface E2E use the default direct fixture and remove their
AppArmor load/unload steps. The focused Runtime Provider lane sets the switch and keeps
its AppArmor preparation. Kubernetes containment conformance remains unchanged.

The switch is test infrastructure configuration only. It is not an Agent, Workspace,
Profile, or product API setting.

## Security

The direct Profile makes no containment claim. The contained Profile remains available
only with the existing AppArmor-backed bwrap deployment. Missing AppArmor reduces the
advertised capability set before Profile selection and does not weaken a selected
Runtime.

The warning contains only Provider identity and the bounded
`apparmor_unavailable` category. Raw Docker daemon security options are not logged.

## Rollout and Compatibility

Existing deployments without containment configuration are unchanged. Compatible
contained deployments are unchanged. A configured Docker Provider on a host without
AppArmor changes from process termination to direct-only registration.

No migration or persisted-state rewrite is required. When host support later becomes
available and the Provider reconnects with containment effective, Runtime Control
records the new capability advertisement through the existing immutable revision
path.

## Test Strategy

- Docker Provider unit tests verify direct registration, contained registration, and
  direct-only effective resolution when AppArmor evidence is absent.
- E2E fixture tests verify direct schema-v1 and contained schema-v2 profile documents.
- Local focused External Channel E2E runs without the containment switch and must enter
  the product journey on a non-AppArmor Docker host.
- Deterministic CI runs without AppArmor preparation.
- Focused Runtime Provider CI sets the containment switch and retains enforcing
  AppArmor evidence.
- Kubernetes containment conformance remains required and unchanged.

Evidence consists of unit results, focused local E2E output, and the existing CI JUnit
and bounded observability artifacts.

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| AppArmor absence terminates a configured Docker Provider | `runtime-260810/REQ-1`, `runtime-260810/ADR-D1` | Direct-only effective registration | Docker Provider startup preflight | Unit test proves registration contract excludes containment |
| Shared E2E fixture always configures contained Docker | `runtime-260810/REQ-4`, `runtime-260810/ADR-D2` | Direct default plus explicit contained lane switch | E2E Provider and Infrastructure Profile fixtures | Fixture unit tests and local non-AppArmor E2E |
| Deterministic and Web Surface CI load AppArmor | `runtime-260810/REQ-4`, `runtime-260810/ADR-D2` | No AppArmor preparation in non-containment lanes | GitHub Actions jobs | Workflow verification and CI logs |
| AppArmor for the current contained implementation | Not removed | Retained under `runtime-260810/ADR-D3` | Focused contained Provider lane | Focused CI fails without enforcing profile |

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Resolve effective containment before Provider lifecycle and registration, retaining direct support when AppArmor is absent | `runtime-260810/REQ-1`, `REQ-2`; `runtime-260810/ADR-D1` | `decided` |
| M2 | Preserve compatibility rejection and prohibit contained-to-direct fallback | `runtime-260810/REQ-3`; `runtime-260810/ADR-D1` | `required` |
| M3 | Default shared E2E to direct Docker and explicitly enable containment only in the focused lane | `runtime-260810/REQ-4`; `runtime-260810/ADR-D2` | `decided` |
| M4 | Retain AppArmor as a prerequisite of the current contained Docker implementation | `runtime-260810/REQ-2`, `REQ-3`; `runtime-260810/ADR-D3` | `decided` |

## Authority Audit

Result: **Passed for Design revision 1.**

- Every Requirement maps to at least one material mechanism.
- Every material mechanism is authorized by confirmed Requirements and accepted ADR
  decisions.
- Effective capability resolution creates no persisted authority or fallback mode.
- The lane switch is trusted test infrastructure and cannot alter product configuration.
- Existing contained security remains unchanged.

## Feasibility Validation

Result: **Feasible.**

- Docker Provider registration already derives schema and capabilities from an optional
  containment configuration.
- Runtime Control already accepts changed Provider capability advertisements and
  Profile compatibility already prevents unsupported Profile selection.
- The E2E Provider and Infrastructure Profile are composed in one shared fixture and
  can consume one lane-level environment switch.
- CI already separates deterministic, focused Runtime Provider, Kubernetes containment,
  and Web Surface lanes.

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-10`
- Approved Design revision: `1`
- Approved authority IDs: `M1`, `M2`, `M3`, `M4`
- Approved scope: Keep Docker Provider direct development available without AppArmor,
  advertise containment only when enforceable, preserve no-fallback security, and
  isolate AppArmor prerequisites to containment-specific E2E.
