---
title: "Direct Google Tools Design Validation"
created: 2026-10-21
updated: 2026-10-21
document_role: supporting
document_type: supporting-design-validation
snapshot_id: google-261021
tags: [google, design, validation, security]
---

# Direct Google Tools Design Validation

- Primary document: [google-261021/DESIGN revision 1](google-261021-direct-workspace-tools.md).
- Requirements: [google-261021/REQ](../requirements/google-261021-direct-workspace-tools.md).
- Decisions: [google-261021/ADR-D1 through ADR-D4](../adr/google-261021-direct-workspace-tools.md).
- Implementation baseline: `81a3503318fac347f687f416f7ac231315e5c5cd`.
- Scope: read-only code/API/SDK research, design authority review, one offline SDK
  probe, and documentation validation. No implementation verification, live
  Google access, database migration, deployment or production-readiness claim.

## Authority Review

Forward review maps ten confirmed requirements to M1-M13 and a verification lane.
Reverse review maps each mechanism to confirmed Requirements, four accepted ADRs,
retained Google/file authority or explicit repository convention. The primary
Design records the full mapping and replacement inventory.

Key consistency checks:

- Actual Google grants, not a selected-action list, determine supported actions
  inside enabled services. Request bundles are not post-consent ceilings.
- Migration preserves actual scopes/account/delegation; newly supported actions
  under existing broad scopes are disclosed. `drive.readonly + drive.file` is not
  whole-Drive write.
- New whole-Drive defaults do not request broader scopes during migration.
- Picker uses a separately issued, actual-scope-verified minimal browser token;
  ordinary multi-service credentials remain server-only. Unexpected rotation has
  exact-current preservation/reconnect handling without overwriting primary scope
  evidence or invalidating newer credentials.
- Scanner removal includes code, tests, acknowledgement gates, persisted DTO
  occurrences and UI claims; normal input/file/account checks remain.
- One drained cutover replaces old contracts, invalidates incomplete attempts and
  preserves historical outcome identity. No rolling compatibility or permanent
  Google MCP fallback is introduced.
- No new operation approval, product versioning, selected-file ACL, general file
  storage system, privileged chat identity or blanket policy-compliance assurance.

Result: no unresolved product choice found in revision 1. Complete Design approval
remains pending; accepted ADR topics are not blanket implementation authority.

## Repository Evidence

Inspected current Google policy/config, encrypted connection and attempt models,
manager publication/reconnect code, current runtime/refresh CAS, canonical Session
and personal Toolkit admission, engine provider/snapshot interfaces, common file
resource authority, Artifact and Runtime transfer paths, management containers,
operator settings, generated-contract ownership and existing Google E2E fixtures.

The stored grant's candidate shape can remain unchanged while task config and
historical final settings transform. Incomplete attempts can be scrubbed without
decrypting their obsolete setup payload. The migration must still validate actual
rows and establish stopped old-writer boundaries before mutation. This evidence
supports a feasible implementation path, not a successful executed migration.

## Official Method Contract Check

The previously downloaded official Gmail v1, Calendar v3 and Drive v3 discovery
JSON contains the selected public resource methods. A narrow lookup validated 29
representative paths: 15 Gmail, 6 Calendar and 8 Drive, including draft/send/filter,
event/freebusy/calendar creation, file mutation/export and permissions changes.
Other method coverage and argument-dependent scope alternatives remain required
implementation tests. Resource ACL/plan/format success is not implied by a method
being present in discovery.

## Offline Public-SDK Probe

The temporary research environment used:

- `google-api-python-client==2.185.0`;
- `google-auth-httplib2==0.2.0`;
- fixture-only credentials and an injected fake HTTP implementation;
- `discovery.build(..., static_discovery=True, cache_discovery=False)`;
- `AuthorizedHttp(..., max_refresh_attempts=0)`;
- `HttpRequest.execute(num_retries=0)`.

No provider network call or real credential was used by the probe. Installing the
research packages used package distribution access; the repository dependency
files were not changed and these are not implementation dependency pins.

| Synthetic send response | Transport requests | Credential refreshes | Observation |
| --- | --- | --- | --- |
| 200 | 1 | 0 | Parsed fixture result |
| 401 | 1 | 0 | Public SDK error, no implicit renewal/replay |
| 503 | 1 | 0 | Public SDK error, no retry |

Building public Calendar event/status, freebusy and calendar-create requests and
Drive copy, permission-create and export requests from bundled API descriptions
made zero transport requests. The probe confirms the SDK transport/retry/static-
construction path, not Google authorization, a bounded streaming implementation,
a live email send, or complete feature behavior.

## Feasibility Classification

- **Feasible local mechanisms:** supported direct-tool/provider composition,
  grant-derived policy, existing account/owner and refresh fencing, independent
  service saves, scanner retirement, known JSON transformation boundaries and
  retained common file services.
- **Conditional implementation evidence:** full scope/prerequisite matrices,
  bounded media transport/parser behavior, format fidelity, callback/migration
  races and complete assembled product E2E.
- **Conditional external evidence:** same-client live API use, strict minimal
  Picker scope receipt and rotation behavior, real selected-file operation,
  Google organization/account/format constraints, and applicable direct-API policy.
- **No live result claimed:** no real Google token issuance or API action occurred.
  No external-policy exemption is inferred from replacing MCP or omitting a scanner.

If strict minimal-token issuance cannot be established with actual evidence, the
Picker lane is blocked until the decision is revisited; no broad-token or browser-
OAuth fallback is silently permitted. Missing optional live prerequisites do not
turn ordinary deterministic CI red, but they leave interoperability explicitly
unverified and prevent unconditional production-readiness claims.

## Documentation Validation

Run from the feature worktree:

```console
python scripts/docs_catalog.py validate
python scripts/docs_catalog.py snapshot google-261021
git diff --check
```

Validate ten REQ headings, unique ADR-D1 through ADR-D4, thirteen authority IDs,
mandatory Design sections, complete Requirement-to-mechanism coverage, relative
links and absence of private provenance. No current Living Spec or implemented
historical snapshot is modified during design-only work. Actual implementation
will update related Specs and run the complete planned verification lanes.
