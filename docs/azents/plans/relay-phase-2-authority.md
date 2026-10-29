---
title: "LLM Backend Phase 2: System Token and Authority"
created: 2026-10-28
tags: [engine, inference, security]
---

# Phase Execution Plan

- Phase: 2/4, durable system-token lifecycle and protected authority API.
- Branch/base: `feat/relay-authority` -> `feat/relay-contracts` (PR #2523).
- PR boundary: token persistence/atomic lifecycle, Admin development issuance, private list/resolve, existing configuration and OAuth binding, generated contracts and owning Specs.
- Inputs: approved relay-261028 Design r1; Phase 1 shared contract package.
- Deliverables: system-admin scoped issuance/rotation/revocation, request-time Agent validation and target resolution, secret-safe protected credential response. Existing Worker unchanged.
- Non-goals: user-managed API keys, duplicated mappings, Proxy runtime/chart, distributed cancellation, Worker migration or live-provider calls.
- Interfaces: opaque token hash lookup, supply-subject lifecycle, exact target resolution, closed provider credential response; add candidate setting DTOs only as required by existing authority, not a new settings source.
- Approved Design mechanisms: M2–M7, M10, M12, M15, M16.
- Authority references: relay-261028/REQ-2–5, REQ-8; relay-261028/ADR-D2–D7, ADR-D10; existing Agent deletion and integration Specs.
- Design delta: None.
- Removal obligations: no existing model/Worker removal. New Agent-owned state must join existing deletion registry and schema verification.
- Absence verification: no public token API, Proxy issuer credential, mapping table, raw-token storage, refresh-token response or transaction held across OAuth I/O.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Token state | Primary | Azents core/RDB/repos/services inference authority | Shared DTOs | hash lookup, atomic rotate/revoke, expiry | deterministic lifecycle and PostgreSQL repository tests |
| Protected routes | Primary | Admin/internal authority routes, config and binding | Token state | system-admin issuer, resolver service auth | route/privilege/secret tests |
| Resolve | Primary | authority services + existing read/OAuth collaborators | Token state | current Agent targets/credentials, final revalidation | authority race/disabled/ownership tests |
| Schema/spec/client | Primary | generated migration/client artifacts, owning Specs | Above | deletion ownership and API contracts | Alembic, generation drift, spec validation |
| Monitoring privacy | Primary | az-common logging integration and tests | Protected credential channel | disable Sentry body/frame-local capture and scrub authority credential fields | integration configuration and nested sentinel tests |

- Integration order: token model/core -> repository/service -> target resolve -> route integration -> tests/generated surfaces/spec.
- Independent review: `/root/relay-reviewer` reviews full stable integrated phase diff; primary applies corrections.
- Final validation: root-owned Ruff/ty/pytest, migration checks where DB available, generated clients and no-leak response/log tests.
- Scope-drift check: same Agent config source, no Proxy mapping replica, resolver cannot issue; no production actions.
- Context checkpoint: Phase 1 #2523 full CI passed (41 checks). Phase 2 implements hash-only lifecycle with Agent/supply/token lock ordering, nonsecret uncertain-issue lookup, separate resolver auth, short prepare/refresh/finalize scopes, closed provider and current-setting projections, generated Admin contracts, schema and owning Specs. Root validation: 41 shared contract tests; 97 server/lifecycle/deletion/OAuth tests against isolated local PostgreSQL; upgrade/check/downgrade/reupgrade/check clean. Final stable rerun: 97 server/deletion/OAuth tests, 84 common-library tests, 41 contract tests and 17 Admin generator-template tests pass. Admin clients regenerated; direct uncached TypeScript client typecheck passes. Ruff/ty, documentation validation and final changed-file pre-commit pass (including propagated testenv lock). The single independent reviewer completed the stable phase review with no findings and no edits/test execution. Commit/PR opening is next. Production/live prerequisites remain unauthorized.
- Local execution detail: normal consumers rotate at five minutes remaining; privileged explicit replacement is allowed at other times but cannot revive revoked/expired predecessors. Disabled/decommissioning Agent admission fails while Admin inspection/revocation still works.
- Privacy discovery: shared logging integration previously allowed Sentry default body and frame-local capture. M12 requires suppressing these collection channels and scrubbing authority-specific nested fields; this changes diagnostic detail, not product authority or provider behavior.
- CI correction: PR #2524 run `40708253882` found the server image did not include the newly editable contract package. Add the package's builder bind mount and runtime source copy in `azents.Dockerfile`; preserve all other build behavior. Local Docker is unavailable, so verify syntax/path/diff and commit hooks, push immediately, then use the new SHA's actual image/E2E CI as validation. This is dependency packaging repair, not a new mechanism; the existing stable phase review remains applicable.
- Credential correction: Phase 3 mapping inspection found `service_account_json` could otherwise carry an authorized-user refresh configuration, executable external-account source or arbitrary token URL. M6/REQ-5 require service-account call material only. Decode a closed Google service-account key shape, fix the Google OAuth token origin, reject refresh/external/unknown fields, and remove unused auth/certificate metadata before protected egress. Normal DTO representations stay redacted and malformed configurations become safe preparation failures. No integration persistence, Worker path or Google login behavior changes. Root validation passed: 50 contract tests, 100 focused server/PostgreSQL/deletion/OAuth tests, full impacted Ruff/ty, docs and pre-commit. The same reviewer's targeted read-only security re-review cleared the 8-file correction with no material findings; no reviewer tests or edits were performed.
