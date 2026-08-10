---
title: "Docker Runtime Provider Development Availability Requirements"
created: 2026-08-10
updated: 2026-08-10
tags: [runtime, provider, docker, development, testenv, security]
document_role: primary
document_type: requirements
snapshot_id: runtime-260810
---

# Docker Runtime Provider Development Availability Requirements

- Snapshot: `runtime-260810`
- Document reference: `runtime-260810/REQ`

## Problem

The Docker Runtime Provider is the primary Runtime Provider for local development, but
the shared E2E fixture currently requires Docker AppArmor support before the Provider
can register. Development Docker environments that do not expose AppArmor therefore
cannot run ordinary Provider-backed development or product E2E journeys even when
those journeys do not require process containment.

## Primary Actor

Azents developer.

## Primary Scenario

A developer starts the Docker Runtime Provider and ordinary deterministic E2E on a
Docker host without AppArmor support. The Provider registers, direct Runtime Profiles
remain selectable and operational, and containment-specific Profiles are reported
unavailable rather than preventing all Provider-backed development.

## Supporting Scenarios

- A compatible Docker host with the enforcing containment profile continues to offer
  contained Runtime Profiles and runs the dedicated containment verification lane.
- A contained Profile never falls back to direct execution when containment support is
  unavailable.
- Web and product E2E journeys that do not verify containment run without an AppArmor
  prerequisite.

## Goals

- Preserve Docker Provider availability in ordinary development environments.
- Keep Provider capability advertisement truthful to the current Docker host.
- Isolate containment-specific prerequisites to containment-specific verification.
- Preserve fail-closed behavior for explicitly contained Runtime Profiles.

## Non-Goals

- Removing the current AppArmor boundary from contained Docker Runtimes.
- Claiming that the current bwrap bootstrap provides equivalent containment without
  AppArmor.
- Adding a weaker or development-only contained Profile.
- Automatically replacing a requested contained Profile with direct execution.
- Changing Kubernetes Runtime Provider containment.

## Requirements

### REQ-1. Baseline Docker Provider availability

The Docker Runtime Provider must remain available for direct Runtime Profiles when the
Docker host does not support AppArmor.

**Acceptance criteria**

- The Provider registers successfully without Docker AppArmor support.
- The Provider advertises and executes the existing direct Docker Profile contract.
- Missing AppArmor does not terminate the Provider process or block unrelated Runtime
  Provider operations.

### REQ-2. Truthful containment availability

The Docker Runtime Provider must advertise process containment only when its configured
containment prerequisites are available on the current Docker host.

**Acceptance criteria**

- A Provider without the required AppArmor support omits the contained Profile schema
  and process-containment capability from its current advertisement.
- A Provider with the required AppArmor support retains the current contained Profile
  advertisement.
- Unavailable containment produces a bounded operator diagnostic without exposing
  credentials or host-sensitive data.

### REQ-3. No containment downgrade

An explicitly contained Runtime Profile must not run through direct execution when
containment is unavailable.

**Acceptance criteria**

- A contained Profile is incompatible or unavailable when the Provider does not
  advertise process containment.
- Existing direct Profiles remain independently available.
- No Runtime lifecycle command silently removes containment from the selected Profile.

### REQ-4. Prerequisite-scoped E2E

E2E lanes must require AppArmor only when the lane verifies Docker process containment.

**Acceptance criteria**

- Ordinary deterministic E2E and Web Surface E2E do not load or require an AppArmor
  profile.
- Their shared Docker Provider fixture publishes a direct Infrastructure Profile.
- The focused Docker containment lane explicitly enables the contained fixture,
  requires AppArmor, and continues to fail when its containment prerequisite is absent.
- Local execution of non-containment E2E can enter the product journey on a Docker host
  without AppArmor support.

## Fixed Constraints

- Existing implemented `runtime-260808` Requirements, ADR, and Design remain immutable.
- PostgreSQL and Runtime Control remain authoritative for Provider resources,
  advertisements, Profile compatibility, and Runtime selection.
- AppArmor absence must not be represented as successful containment.
- Credentials, raw Docker daemon responses, and host-sensitive paths must not enter
  Provider diagnostics or E2E evidence.

## Open Assumptions

- The current AppArmor-backed contained Docker implementation remains the supported
  containment implementation until a separately approved and qualified replacement
  exists.

## Confirmation

Confirmed by the requester on 2026-08-10 before ADR and design decisions began.
