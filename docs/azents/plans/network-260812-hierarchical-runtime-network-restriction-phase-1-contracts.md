---
title: "Hierarchical Runtime Network Restriction Phase 1 Contracts Plan"
created: 2026-08-12
tags: [runtime, network, security, provider, workspace]
---

# Phase Execution Plan

- Phase: `1/8 — Hierarchical Profile contracts and composition`
- Branch/base: `feature/network-restriction-1-contracts` → `origin/main`
- PR boundary: Add Kubernetes Profile v3, Workspace Policy v2, canonical domain and
  CIDR hierarchy, mode-aware capabilities, and mode/input-aware application impact
  without changing Runtime Control protocol or Kubernetes Provider execution.
- Inputs: Confirmed `network-260812/REQ`, accepted `network-260812/ADR-D1`,
  `ADR-D2`, and `ADR-D8`, approved `network-260812/DESIGN` revision `1`, current
  Profile v1/v2 and Policy v1 direct behavior.
- Deliverables: Strict typed v3/v2 contracts; canonical exact/wildcard domain model;
  inherited CIDR/domain composition; bounded expansion errors; legacy-to-v3 Policy-v2
  resolution; mode-aware required capabilities and compatibility; mode-aware
  application impact; focused tests; approved snapshot and implementation plans.
- Non-goals: Protobuf or Provider protocol changes, Provider diagnostics persistence,
  Kubernetes resource manifests, CA generation, proxy image/addon, Runner trust,
  Helm settings/RBAC, API/OpenAPI changes, generated clients, web UI, E2E, Specs, or
  implementation dates.
- Interfaces: Profile v3 uses discriminated `network_access` variants `direct`,
  `proxy_required`, and `no_network`. Policy v2 uses discriminated
  `network_restriction` variants `inherit`, `direct`, `proxy_required`, and
  `no_network`. Policy v2 always resolves Kubernetes input to a canonical effective
  Profile v3. Profile v1/v2 and Policy v1 remain unchanged direct contracts. Exact
  hosts and leading-label wildcards canonicalize to lowercase IDNA ASCII without one
  trailing root dot. Domain mode is explicit. Inherited denials are final. Expansion
  errors remain bounded server reason codes. Strict Docker policy is incompatible and
  never falls back to direct. Classification returns in-place only for direct CIDR,
  proxy destination CIDR, proxy domain, and proxy artifact-only inputs described by
  Design; mode, trust, hosts, Runtime Pod, and unrelated Provider inputs recreate.
- Approved Design mechanisms: `M1`, `M2`, `M11`
- Authority references: `network-260812/REQ-1`, `REQ-2`, `REQ-4`, `REQ-9`,
  `REQ-10`; `network-260812/ADR-D1`, `ADR-D2`, `ADR-D8`; approved Design contract,
  canonical-domain, capability, desired/applied, and application-impact sections.
- Design delta: `None`
- Removal obligations: Remove v1/v2 `network_policy` as the only supported shape for
  new Kubernetes contracts and Policy v1 as the only Workspace policy version.
  Retain every legacy parser and direct behavior explicitly required by M1.
- Absence verification: Parsing tests require v3 for strict modes and reject
  mode-specific unknown fields; Policy-v2 tests produce v3 effective documents from
  legacy and v3 infrastructure Profiles; searches and tests show no strict mode is
  represented through legacy `network_policy` or Policy v1; legacy fixture digests
  remain stable.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Profile and policy types | `/root` | `python/apps/azents/src/azents/core/runtime_profile.py`, focused tests | approved M1 contract | v3 network union, Policy-v2 union, parsers, canonical serialization | targeted pytest, Ruff, ty |
| Canonical domain and hierarchy | `/root` | same core module and focused tests | ADR-D2 and v3/v2 types | IDNA exact/wildcard normalization, structural subset, deny-final composition | vector and invalid-input tests |
| Resolution and Workspace validation | `/root` | `azents/services/runtime_profile_resolution/**`, `azents/services/runtime_profile_workspace/**`, focused tests | canonical composition interface | version-aware policy parsing and ready/blocked effective v3 output | targeted service tests |
| Capability and impact | `/root` | core Profile compatibility/classifier and focused compatibility/reconciliation tests | effective v3 contract | mode capabilities and exact in-place/recreate decisions | parametrized compatibility and impact tests |
| Documentation | `/root` | approved snapshot trio and `docs/azents/plans/network-260812-*.md` | approved Design | tracked authority baseline and execution plan | docs validators, diff check |
| Independent review | `/root/network-260812-reviewer` | read-only Phase 1 diff | stable implementation and focused evidence | authority, compatibility, hierarchy, classification, and scope report | written review findings |

- Integration order: v3/v2 typed variants → canonical domain vectors → hierarchy
  composition → version-aware service parsing → capability derivation → application
  impact classification → focused validation → independent review → corrections →
  final validation.
- Independent review: `/root/network-260812-reviewer` reviews read-only against
  Requirements, ADR-D1/D2/D8, Design `M1`/`M2`/`M11`, current Runtime Provider and
  Workspace Specs, this plan, focused test evidence, and the stable diff. It reports
  only material authority, fail-closed hierarchy, legacy-compatibility, digest,
  application-impact, removal, and scope-drift findings.
- Final validation: affected backend Ruff and format checks; configured `ty`; targeted
  core Profile, compatibility, resolution, Workspace Profile, reconciliation, and API
  model regression tests that do not require generated contract changes; documentation
  snapshot/index validation; `git diff --check`.
- Scope-drift check: Confirm complete `M1`/`M2`/`M11` contract behavior and both
  removal obligations. Confirm no protobuf, Kubernetes execution, diagnostics
  persistence, proxy/CA/Runner/Helm/API/UI/E2E/Spec behavior, legacy rewrite, direct
  fallback, hot reload, Agent override, or new persistent state is added.
- Context checkpoint: Phase started from `4c6ce08f4` on
  `feature/network-restriction-1-contracts`. The stable implementation adds canonical
  Profile v3 and Policy v2 unions, IDNA exact/wildcard hierarchy, effective-Profile
  capability validation, and mode/input-aware impact classification. Legacy v1/v2
  Profile semantic JSON and digests round-trip unchanged; Policy v1 remains direct-only.
  Final evidence is repository-wide backend Ruff format/lint and configured `ty`,
  4,279 backend tests, 70 focused Profile/service tests, 14 documentation validator
  tests, `git diff --check`, strict-shape absence search, and legacy digest round-trip.
  Regenerated Public and Admin OpenAPI files are byte-identical to `4c6ce08f4`; their
  SHA-256 values remain `e3fbc601d21f3f139edfef1253cc0dfc415686fcb622254d0eb190d05ac831af`
  and `e3ea3a4ff354c8a0fc18f7f13a855c29394eff1ce9028cd479429cfb9a7ed493`.
  No protocol, Provider resource, persistence, Helm, API projection, generated client,
  UI, E2E, or Spec behavior is present. Phase 2 begins only after this PR is open and
  consumes the exact canonical v3 shape, capability names, bounded errors, and
  classifier behavior recorded here.
