---
title: "ADR-0144: OSS Admin Surface Authentication and Bootstrap"
created: 2026-07-13
tags: [architecture, frontend, backend, auth, admin, oss, security]
---

# ADR-0144: OSS Admin Surface Authentication and Bootstrap

## Context

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

ADR-0065-D5 placed first-owner bootstrap in the public product flow and created a first Workspace. That
shape couples instance authority to Workspace ownership and exposes installation setup on the product
surface. A separate instance-wide authorization model is required for Admin operations.

## Decision

### Keep the Admin surface separate and routing-neutral

The Admin Web remains a separately built and deployed surface. Azents does not require a particular
relationship between the Main Web, Admin Web, Public API, and Admin API URLs. Each component receives the
base/public URLs it needs through configuration.

The Main Web may show a link to the configured Admin Web URL when the current user has Admin-surface
access. It does not bundle Admin UI code, depend on `@azents/admin-client`, or proxy Admin API operations.
Workspace-scoped administration continues to use Public API permissions.

### Use the Azents account system for Admin authentication

The Admin surface uses the same Azents user identity, login, refresh, logout, and access-token semantics
as the Main Web. It does not use GitHub organization membership as its account system.

The two web surfaces are not required to share browser cookies. Each surface may maintain host/path-safe,
separately named HTTP-only cookies while authenticating the same backend user. Shared-cookie SSO or a
one-time session handoff can be designed later as an optional UX improvement.

Every non-bootstrap Admin API operation requires an Azents user access token and backend-enforced
system-admin authorization. Admin Web tRPC procedures also require an Admin Web session before proxying
requests, but the Admin API remains the authoritative security boundary. Machine OAuth2 and unauthenticated
Admin API modes are removed rather than retained as compatibility fallbacks. External gateways and
network policies remain optional defense in depth.

### Represent instance authorization separately from Workspace membership

System roles are stored in a `system_user_roles`-style relation, not in Workspace membership and not as a
boolean column on `users`. The initial role set contains only `system_admin`; the relation can add future
instance roles without changing the User table.

A Workspace OWNER is not implicitly a system admin. System admins can list assignments, grant
`system_admin` to an existing user, and revoke it from another system admin. The backend prevents removal
of the final system admin. The Admin Users surface exposes these actions alongside existing user lookup.

### Move initial bootstrap to the Admin surface

The public Main Web first-owner setup flow is removed. Bootstrap belongs to the Admin Web and Admin API.
The bootstrap endpoints are exceptional unauthenticated endpoints that require a high-entropy one-time
setup token and are available only while the instance has no users.

Bootstrap creates the first Azents user with a verified primary email and password, grants
`system_admin`, and creates an ordinary Azents session. It does not create a Workspace or Workspace
membership. The system admin creates a Workspace later through the normal Main Web flow when needed.

A standalone installation may generate a setup token, persist only its hash, and print the plaintext once
to startup logs. Operators can instead provide the token through environment or Kubernetes Secret
configuration; configured secrets are not logged. The token is never a user access or refresh token and
is consumed only after successful bootstrap.

Bootstrap never reopens because all system-admin assignments were lost. Existing installations with
users and installations requiring recovery use the same explicit break-glass CLI command to grant
`system_admin` to an existing user selected by exact email. The CLI does not create users, and Azents does
not auto-promote the oldest user, a Workspace owner, or an environment-selected user.

This bootstrap decision supersedes only the first-owner bootstrap shape in ADR-0065-D5. Signup-token
registration and Workspace invitation decisions in ADR-0065 remain unchanged.

### Preserve the current operator surface behind the new boundary

The v1 Admin Web and Admin API continue to support global Users, User Emails, Workspaces, Workspace
Members, signup tokens, password-reset tokens, email-verification inspection, system model-catalog
operations, and Debug functions. Debug remains an authenticated system-admin capability.

Testenv remains dedicated to automated test fixtures and prerequisites. Operator-facing Debug functions
are not moved into or replaced by testenv.

## Consequences

- OSS operators use one Azents identity system while Admin authorization remains instance-scoped.
- Admin Web and Main Web remain independently deployable and do not require a fixed ingress topology.
- A stolen or exposed Admin Web route cannot rely on a shared service credential to act as an operator;
  the Admin API verifies the actual user and role on every request.
- Main Web continues to use Public API workspace permissions and does not regain global Admin API access.
- Deployments with existing users must run the break-glass CLI once to nominate their first system admin.
  Admin API requests remain unavailable until that explicit grant is made.
- Initial installation authority and Workspace ownership become independent. This intentionally replaces
  the prior public first-owner bootstrap behavior.
- The system gains a role relation, bootstrap-token state, Admin authentication migration, and associated
  API/client/Helm/E2E work.
- Logging a bootstrap token is acceptable only for the one-time generated setup secret. User tokens,
  configured bootstrap secrets, signup tokens, and password-reset tokens must never be logged.

## Alternatives Considered

### Merge Admin UI and Admin API access into Main Web

Rejected. It increases frontend routing and authorization blast radius and would encourage global Admin
operations to cross the workspace product boundary. Workspace-scoped product administration already has
Public API equivalents.

### Keep GitHub organization login or machine OAuth2

Rejected. It preserves a second identity system and leaves Admin actions attributable to a shared client
rather than an Azents user. External identity-aware proxies remain optional defense in depth, not the
source of application authorization.

### Derive system admin from Workspace OWNER

Rejected. Workspace ownership is tenant-scoped and must not imply authority over all users, credentials,
Workspaces, model catalogs, or operational diagnostics.

### Store a boolean on User

Rejected. A role relation supports future instance-scoped roles and records grant provenance without
redefining the User account schema.

### Reopen bootstrap when no system admin remains

Rejected. An authenticated or database-loss condition must not turn an unauthenticated setup endpoint
back into an instance ownership-claim path. Recovery requires explicit server/database operator access.

### Automatically promote an existing user during upgrade

Rejected. Creation order and Workspace ownership are not evidence of instance-operator intent. Exact-email
CLI selection makes the privilege grant explicit and auditable.

### Move Debug functions into testenv

Rejected. Testenv supports automated tests, while Admin Debug endpoints are operator diagnostics that must
remain available in a system-admin-protected production Admin surface.
