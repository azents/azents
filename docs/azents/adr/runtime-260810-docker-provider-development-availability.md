---
title: "Docker Runtime Provider Development Availability"
created: 2026-08-10
tags: [runtime, provider, docker, development, testenv, security, architecture]
document_role: primary
document_type: adr
snapshot_id: runtime-260810
---

# Docker Runtime Provider Development Availability

- Snapshot: `runtime-260810`
- Document reference: `runtime-260810/ADR`
- Requirements: [Docker Runtime Provider Development Availability Requirements](../requirements/runtime-260810-docker-provider-development-availability.md) (`runtime-260810/REQ`)
- Decision mode: Requester-directed
- Decision owner: requester

## Context

The Docker Provider already has separate direct and contained Profile contracts, but a
deployment-configured containment backend currently makes AppArmor support a
Provider-process startup prerequisite. The shared deterministic and Web Surface E2E
fixture always configures that backend, so unrelated development journeys inherit the
containment prerequisite.

## Decision Map

- [x] `runtime-260810/ADR-D1` — Keep the Provider registered and reduce unsupported capability advertisement
- [x] `runtime-260810/ADR-D2` — Split ordinary and containment E2E fixture policy
- [x] `runtime-260810/ADR-D3` — Retain AppArmor for the current contained implementation

## Decisions

### runtime-260810/ADR-D1: Keep the Provider registered and reduce unsupported capability advertisement

**Affected requirements:** `runtime-260810/REQ-1`, `REQ-2`, `REQ-3`

The Docker Provider resolves its effective containment support from trusted deployment
configuration and current Docker daemon security-option evidence before registration.
When containment is configured but required AppArmor support is unavailable, the
Provider remains connected and advertises only its direct Profile contract.

Profile compatibility rejects contained Profiles because the current advertisement
does not include their schema or capability. Runtime lifecycle execution does not
rewrite, downgrade, or reinterpret a contained Profile as direct execution.

**Rejected alternatives:**

- Terminating the Provider process was rejected because it removes unrelated direct
  development capability.
- Advertising containment and failing only when a Runtime starts was rejected because
  the advertisement would claim unavailable host capability.
- Automatically running a contained Profile through direct execution was rejected
  because it weakens an explicit security contract.

### runtime-260810/ADR-D2: Split ordinary and containment E2E fixture policy

**Affected requirements:** `runtime-260810/REQ-4`

The shared E2E Docker Provider fixture defaults to the direct Profile contract. A
trusted lane-level test environment switch explicitly enables the existing contained
Provider configuration and contained Infrastructure Profile only for focused
containment verification.

Ordinary deterministic and Web Surface lanes do not prepare AppArmor. The focused
Runtime Provider containment lane prepares AppArmor, enables the contained fixture,
and retains fail-closed prerequisite behavior.

**Rejected alternatives:**

- Detecting pytest test names inside the session fixture was rejected because fixture
  security mode would depend on incidental collection structure.
- Skipping the entire E2E suite when AppArmor is absent was rejected because unrelated
  product behavior remains runnable.
- Treating a local missing prerequisite as passing containment evidence was rejected
  because it would create false security evidence.

### runtime-260810/ADR-D3: Retain AppArmor for the current contained implementation

**Affected requirements:** `runtime-260810/REQ-2`, `REQ-3`; fixed security constraint

The current contained Docker implementation continues to require the dedicated
enforcing AppArmor profile. The existing bwrap backend isolates the Agent child, while
the AppArmor profile constrains the privileged set-user-ID bwrap bootstrap and its
bounded capability set. Removing that boundary requires a separate security design and
qualification proving an equivalent bootstrap boundary.

**Rejected alternatives:**

- Making AppArmor optional inside the same contained Profile was rejected because one
  Profile would then represent materially different security guarantees.
- Removing AppArmor based only on Agent-child bwrap qualification was rejected because
  that evidence does not qualify the privileged bootstrap boundary.

## Consequences

- Standard development Docker hosts can run direct Provider-backed journeys.
- Provider advertisements describe actual host capability without creating a new
  persistent state or fallback mode.
- Containment-specific CI remains stricter than ordinary product E2E.
- A future bwrap-only or alternate-backend containment implementation requires a new
  Requirements and ADR snapshot.
