---
title: "Runtime Web Service Management Requirements"
created: 2026-09-15
updated: 2026-09-15
implemented: 2026-09-15
tags: [runtime-web, runtime, frontend, agent]
document_role: primary
document_type: requirements
snapshot_id: webservice-260915
---

# Runtime Web Service Management Requirements

- Snapshot: `webservice-260915`
- Document reference: `webservice-260915/REQ`

## Problem

Runtime Web services are currently managed as Session-scoped approval resources even though multiple Sessions use the same Agent Runtime and its concrete local ports. This can present duplicate service identities for one real port, produces longer opaque service addresses, and exposes an approval-oriented workflow that does not match direct user management.

Users need one understandable service list for the Agent Runtime, with direct control over whether each local application is publicly reachable and for how long. Agents need a smaller tool surface that can create or locate a service and direct the user to the same human-controlled activation flow without gaining deletion or exposure-extension authority.

## Primary Context

### Primary Actor

An authorized user who wants to open or share an application running on a local port of an Agent Runtime.

### Primary Scenario

An Agent identifies an application port and requests a web service. If the service does not exist, it appears in the shared service list in the Off state. The Agent gives the stable service URL to the user and asks the user to turn it On. The user can reach the same management state from the Session side panel, Agent settings, or the service URL, choose a finite exposure duration, turn the service On, use the public URL, reset or stop the exposure, and delete the service when it is no longer needed.

## Supporting Scenarios or Effects

- A user can add and manage a service directly without an approval or rejection workflow.
- Every Session using the same Agent Runtime observes the same service for a given local port.
- Removing the Agent Runtime removes its services, and no service management capability is shown while the Agent has no Runtime.
- Deleting a service or permanently removing its Agent Runtime retires that public address; recreating the service produces a new short address.

## Goals

- Give users one consistent service-management model based on direct On/Off control.
- Prevent multiple Sessions from representing the same Runtime port as independent services.
- Keep each service URL short and stable for the lifetime of that service.
- Make exposure duration and expiration recovery explicit and predictable.
- Keep destructive service deletion under human control.
- Reduce the Agent tool surface to the actions the Agent can safely perform.

## Non-Goals

- Starting, stopping, or supervising the application process listening on the local port.
- Allowing an Agent to delete a service.
- Preserving services after permanent Agent Runtime removal.
- Preserving a public address after its service is deleted.
- Recording or presenting whether a service was originally created by a user or an Agent.
- Providing indefinite public exposure.
- Exposing hostname hashing or internal ownership terminology in the normal management UI.

## Requirements

### REQ-1. One service per Agent Runtime port

A local port of an Agent Runtime must have one service identity shared by every Session that uses that Runtime.

**Acceptance criteria**

- Two Sessions using the same Agent Runtime and local port observe and manage the same service.
- A state change made through one Session is visible through the other Session and Agent settings.
- A different port remains an independently manageable service.
- Service management is not shown when the Agent has no Runtime.
- Permanent Agent Runtime removal removes every service belonging to that Runtime.

### REQ-2. Short service-lifetime address

A service must have a short public address that remains stable while the service exists.

**Acceptance criteria**

- Repeated lookup and On/Off changes for an existing service return the same URL.
- The hostname key contains exactly 12 lowercase DNS-safe characters.
- Different existing services have different URLs.
- The address is suitable for use as a public HTTPS hostname.
- Deleting and recreating a service produces a new URL.
- Permanently removing and later recreating the Agent Runtime and service produces a new URL.

### REQ-3. Shared human management surfaces

An authorized user must be able to manage the same service state from both the Session side panel and Agent settings.

**Acceptance criteria**

- Both surfaces show the same service names, ports, URLs, On/Off state, selected duration, and current expiration.
- Changes made through either surface are reflected in the other.
- The management UI explains that a web service gives an application on a local port a public URL.
- The normal UI does not display creation-origin labels, hostname-generation details, or internal ownership terminology.

### REQ-4. Direct service creation and deletion

An authorized user must be able to add and delete services directly without an approval or rejection workflow.

**Acceptance criteria**

- Creating a service does not require a second approval action.
- The user can choose whether a newly created service is turned On after creation.
- The user can delete an existing service from either management surface.
- Deletion turns Off the public URL and removes the service from all management surfaces.
- Services do not retain or expose user-created versus Agent-created provenance.

### REQ-5. On/Off exposure control

Service exposure must be controlled by one direct On/Off state rather than approval, rejection, pending, resume, or close-cycle states in the user interface.

**Acceptance criteria**

- Turning a service On makes its public URL available when the Runtime application is reachable.
- Turning a service Off stops public access without deleting the service.
- An expired service becomes Off.
- Turning an Off service On starts a new exposure window.
- No approval-request or rejection state is shown in the service list.

### REQ-6. Finite and explicit expiration

The user must control each service exposure using a duration of 1 hour, 6 hours, or 24 hours.

**Acceptance criteria**

- Each service offers exactly the 1-hour, 6-hour, and 24-hour duration choices.
- A service first created by an Agent has 1 hour selected.
- Turning On starts the selected duration from the moment the service becomes On.
- The UI shows the current expiration while the service is On.
- Resetting expiration starts a new window of the selected duration from the reset moment.
- Turning Off and later On starts a new window using the selected duration.
- Changing the selected duration while On does not alter the current expiration until the user resets expiration or performs a later Off-to-On transition.

### REQ-7. Service URL activation path

An authorized user who opens an Off service URL must be able to turn the service On through that URL instead of depending on a separate pending approval resource.

**Acceptance criteria**

- An unauthenticated user follows the existing Runtime Web authentication flow.
- An authenticated and authorized user opening an Off service URL sees a direct turn-On action with the duration controls.
- After the user turns the service On, the same URL opens the proxied application.
- Opening the URL does not create or renew a separate approval request.

### REQ-8. Bounded Agent service tools

The Agent service tool surface must consist of request, list, and close actions.

**Acceptance criteria**

- Request creates a missing service in the Off state or returns the existing service without changing its current On/Off state or expiration.
- Request returns the stable URL and explicitly instructs the Agent to give that URL to the user and ask the user to turn the service On.
- List returns the services and their current user-relevant state.
- Close is idempotent and turns an On service Off; calling it for an already-Off service succeeds without creating another state.
- There is no separate prepare or cancel-request action.
- The Agent has no service-delete action.
- Agent actions cannot extend or reset an existing exposure window.

### REQ-9. Preserve Runtime Web security boundaries

The revised service-management model must retain the existing Runtime Web authentication, authorization, isolation, and application-data handling guarantees.

**Acceptance criteria**

- Only an authorized user can manage or activate a service.
- Public application traffic continues to be isolated from Main Web credentials.
- Application request and response content is not retained as product history.
- Existing protections for unsafe targets, credentials, origins, redirects, framing authority, Service Workers, and bounded HTTP, SSE, and WebSocket traffic remain effective.
- An Off, deleted, expired, or Runtime-less service cannot proxy application traffic.

## Fixed Constraints

- The Agent Runtime is the service availability boundary; no Runtime means no service capability.
- Service identity is unique for one Agent and numeric local port while the service exists.
- Public hostname keys are short random DNS-safe identifiers and are not authentication credentials.
- Exposure is always finite and limited to the supported duration choices.
- Creation provenance is not product state and must not affect later presentation, authorization, or behavior.
- Service deletion remains a human-only capability.

## Open Assumptions

- Existing workspace and Agent authorization rules determine which authenticated users may manage services.
- Exact navigation placement within Agent settings is a frontend design detail as long as the service-management surface is directly reachable.
- Random identifier generation and collision retry are technical design decisions that must preserve the 12-character hostname contract.

## Confirmation

Confirmed by the requester on 2026-09-15 before ADR and design decisions began.
The requester confirmed the 1-hour Agent-created-service default on the same date
before the first material ADR decision.
The requester replaced deterministic recreation with a 12-character random
service-lifetime address and reconfirmed REQ-2 on the same date.
