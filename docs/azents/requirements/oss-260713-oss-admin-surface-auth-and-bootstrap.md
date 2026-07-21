---
title: "OSS Admin Surface Authentication and Bootstrap Historical Requirements Reconstruction"
created: 2026-07-13
implemented: 2026-07-13
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: oss-260713
historical_reconstruction: true
migration_source: "docs/azents/adr/0144-oss-admin-surface-auth-and-bootstrap.md"
---

# OSS Admin Surface Authentication and Bootstrap Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `oss-260713`
- Source: `docs/azents/adr/oss-260713-oss-admin-surface-auth-and-bootstrap.md`
- Historical source date basis: `2026-07-13`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

Azents originally separated the Admin Web and Admin API for a SaaS operating model. The Admin Web uses
GitHub organization membership for its browser login, while its server-side tRPC layer calls the Admin
API with a shared machine credential or without application authentication. The tRPC procedures do not
validate an Azents user session. This makes the current browser login a UI gate rather than a complete
server-side authorization boundary and creates a confused-deputy risk if an unauthenticated caller can
reach the tRPC routes.

The main product web now uses only the Public API. Reintroducing the Admin API client there would allow a
workspace user interface to proxy global operations that are not guarded by workspace membership. The
Public API already provides workspace-scoped member, invitation, and join-request operations with
backend-enforced workspace permissions, so product administration does not require Admin API access.

Open-source deployments need an operator experience that does not require a second account directory,
GitHub organization membership, or an external OAuth proxy. They also use different routing topologies:
path prefixes, separate domains, direct ports, and custom gateways must all remain valid.

[signup-260617/ADR-D5](../adr/signup-260617-signup-token-registration.md) placed first-owner bootstrap in the public product flow and created a first Workspace. That
shape couples instance authority to Workspace ownership and exposes installation setup on the product
surface. A separate instance-wide authorization model is required for Admin operations.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
