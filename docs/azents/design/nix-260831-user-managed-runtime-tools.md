---
title: "User-Managed Runtime Tool Addon Design"
created: 2026-08-31
tags: [runtime, package-management, nix, architecture, security]
document_role: primary
document_type: design
snapshot_id: nix-260831
---

# User-Managed Runtime Tool Addon Design

- Snapshot: `nix-260831`
- Document reference: `nix-260831/DESIGN`
- Requirements: [nix-260831/REQ](../requirements/nix-260831-user-managed-runtime-tools.md)
- Decisions: [nix-260831/ADR](../adr/nix-260831-user-managed-runtime-tools.md)
- Related design: [runtime-260831/DESIGN](./runtime-260831-persistent-system-tools.md)
- Mode: Collaborative
- Decision owner: Requester

## Current Behavior and Gap

The Phase 2 Runner implementation provides a pinned Nix release, a pinned initial
Nixpkgs source, signed-cache defaults, persistent `/nix` storage, native Agent
profiles, bootstrap integrity checks, and Runtime prompt guidance.

The implementation originally described `max-jobs=0`, signature settings, and the
release registry as enforced policy. Direct single-user Nix does not provide that
boundary when the Agent owns the store and invokes the unrestricted native CLI.
The gap is therefore documentation and authority alignment, not loss of the native
addon behavior requested by `runtime-260831/REQ`.

## Requirement and Decision Traceability

| Requirement | Design mechanisms | ADR authority |
| --- | --- | --- |
| `nix-260831/REQ-1` | Release-provided initial defaults with native Agent override | D1 |
| `nix-260831/REQ-2` | Existing Runtime user, filesystem, container, and network sandbox remains authoritative | D1; current Runtime Specs |
| `nix-260831/REQ-3` | Default Nix config, state, cache, profile, and store paths remain under persistent `/nix` | D1; `runtime-260831/REQ-2`, `REQ-5` |

## Architecture and Ownership

The Runner release continues to own only the initial addon experience:

- bundled Nix CLI closure and bootstrap artifacts;
- initial pinned Nixpkgs registry;
- initial substituter, signature, and build defaults;
- bootstrap generation and release-root reconciliation; and
- concise native command guidance.

The Agent owns post-startup native Nix use inside its Runtime. This includes package
profiles, user configuration, registries, environment variables, and command
options. The Nix store and database are physical Runtime state, not a Platform
package-management source of truth.

No new service, daemon, sidecar, wrapper, API, database row, capability, Profile,
Admin setting, or package inventory is introduced.

## Runtime Defaults and Agent State

The release defaults remain conservative:

- signed `cache.nixos.org` substitution is configured;
- local builds and fallback realization are disabled by default;
- the initial `nixpkgs` alias points to the release-pinned local catalog;
- release and catalog roots remain garbage-collection roots; and
- bootstrap seed imports remain verified against the image manifest.

These are defaults, not enforcement. The Agent may replace or override them through
native Nix behavior.

Default Agent Nix paths remain under `/nix`:

- profile: `/nix/var/state/azents-agent/nix/profiles/profile`;
- user state: `/nix/var/state/azents-agent`;
- user configuration: `/nix/var/config/azents-agent`;
- cache: `/nix/var/cache/azents-agent`;
- store, database, logs, and release configuration: existing `/nix` paths.

This keeps addon state outside ordinary Agent Workspace content while allowing it to
persist with the dedicated Nix store.

## Bootstrap Integrity Boundary

Runner startup remains responsible for making the bundled addon baseline usable
before Runtime registration. It verifies image artifact digests, initializes or
reconciles the release closure, validates release and catalog closure contents, and
advances managed release roots only after successful validation.

This integrity boundary proves that the release baseline is usable at startup. It
does not continuously police Agent changes after readiness. A later Agent change
may cause a native Nix command or future bootstrap validation to fail; explicit
Runtime reset remains the destructive recovery boundary.

## Security and Network Boundary

Agent customization does not change the surrounding Runtime sandbox:

- no added Linux capability, privilege escalation, Provider credential,
  ServiceAccount, host filesystem, or host package database;
- direct, proxy-required, and no-network policy remains external authority;
- installed executables run as the existing Runner user; and
- the addon does not claim supply-chain isolation from the Agent itself.

## Migration and Rollout

The existing Phase 1 Provider storage contract remains valid. Phase 2 changes only
the authority description and the default user configuration path; no Provider,
database, API, or generated-client migration is required.

Existing Nix stores gain the default user configuration directory at the next
Runner startup. Release generation reconciliation may refresh release-owned default
files while leaving Agent profiles, user configuration, and installed store paths
in place.

## Failure, Retry, and Recovery

- Release seed or closure corruption fails Runner readiness.
- Ordinary package and Agent-configuration errors remain native command failures.
- Agent overrides may enable behavior outside the release defaults, including local
  realization; Azents does not report this as a policy bypass.
- Existing Runtime network and storage failures remain authoritative.
- Explicit Runtime reset recreates the initial release-default state.

## Observability

Runner logs retain bounded bootstrap generation and integrity outcomes. Azents does
not log or inventory Agent-selected registries, options, packages, or command
history as managed package policy.

## Test Strategy

### E2E primary verification

The existing `runtime-260831` Kubernetes matrix remains primary for default addon
behavior: native search, install, execution, persistence, reset, no-network
behavior, prompt guidance, and Workspace separation.

The E2E contract verifies release defaults and observable Runtime behavior. It does
not claim that an Agent cannot override native Nix settings.

### Focused Runner and Server verification

- Bootstrap artifact and closure integrity, interrupted recovery, and release-root
  reconciliation.
- Default native profile, config, state, cache, registry, and PATH locations under
  `/nix`.
- Conservative release defaults and pinned initial catalog.
- Agent configuration path persistence outside Workspace.
- Exact Runtime prompt guidance and shell-disabled/runtime-free absence.
- Absence of daemon, wrapper, capability, Profile, API, database, Admin, and
  package-inventory surfaces.

## Alternatives

The separate policy service, wrapper, and Nix abandonment alternatives are rejected
by `nix-260831/ADR-D1`.

## Assumptions and Non-Blocking Risks

- Agent customization can reduce reproducibility and enable expensive local builds.
- User-selected package sources have the same trust implications as other
  Agent-selected downloads and executable code inside the Runtime.
- The default pinned catalog remains useful without being an exclusive authority.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Runner release provides conservative initial Nix configuration, cache trust, and pinned catalog defaults without enforcing them against the Agent | `nix-260831/REQ-1`; ADR-D1 | `decided` |
| M2 | Direct same-UID native Nix remains the Agent interface with no daemon, wrapper, or package-management control plane | `nix-260831/REQ-1`, `REQ-2`; ADR-D1; `runtime-260831/ADR-D1`, `ADR-D2` | `decided` |
| M3 | Default Agent Nix configuration, state, cache, profile, and store paths persist under Provider-owned `/nix` outside Workspace | `nix-260831/REQ-3`; `runtime-260831/REQ-2`, `REQ-5` | `derived` |
| M4 | Bootstrap validates the release baseline before registration but does not continuously enforce package policy after readiness | `nix-260831/REQ-1`, `REQ-2`; ADR-D1; `runtime-260831/REQ-7` | `derived` |
| M5 | Runtime prompt documents native convenience commands without claiming Platform package-policy enforcement | `nix-260831/REQ-1`; `runtime-260831/REQ-4`; ADR-D1 | `derived` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Claims that release Nix settings are enforced against the Agent | `nix-260831/REQ-1`; ADR-D1 | Release-provided Agent-overridable defaults | Phase 2 documentation, tests, and checkpoint update | No prompt, plan, test, or Spec claims binary-only or exclusive-catalog enforcement |
| Agent user-registry default under the home Workspace | `nix-260831/REQ-3` | Default `NIX_CONFIG_HOME` under persistent `/nix` | Phase 2 Runner environment update | Environment tests and Workspace separation validation |
| Separate policy daemon, wrapper, package inventory, or Admin configuration | None | Remains absent under ADR-D1 | None | Source, schema, migration, API, generated-client, and deployment diff review |

## Feasibility

- **REQ-1 — Feasible:** the implemented native CLI already accepts release defaults
  and Agent overrides; the local-build counterexample proves the addon is not an
  enforcement boundary.
- **REQ-2 — Feasible:** existing container, privilege, filesystem, and network
  controls remain unchanged.
- **REQ-3 — Feasible:** Runner environment already relocates Nix state and cache
  under `/nix`; adding the user configuration path uses the same persistent
  boundary.

No authority or feasibility blocker remains for revision `1`.

## Design Approval

- Mode: `Collaborative`
- Decision owner: Requester
- Approved on: `2026-08-31`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: Nix remains a direct native user-managed Runtime convenience
  addon with Agent-overridable release defaults, persistent state outside
  Workspace, existing Runtime security/network authority, and no package policy
  management plane.
