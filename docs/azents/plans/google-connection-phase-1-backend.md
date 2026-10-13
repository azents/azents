---
title: "Google Connection Phase 1 Backend Execution Plan"
created: 2026-10-13
tags: [google, backend, oauth, testing, implementation]
---

# Phase Execution Plan

- Phase: 1, backend.
- Branch/base: `design/google-261013-connection` → `main`.
- PR boundary: existing #2252, Google connection [1/3]: backend.
- Inputs: [approved Design revision 4](../design/google-261013-connection.md),
  [Requirements](../requirements/google-261013-connection.md), accepted snapshot
  ADR-D1 through ADR-D4, direct activation and explicit fresh-renewal clarifications.
- Deliverables: redacted operator configuration; typed task/scoped capability
  policy and content screening; exact unpublished OAuth; partial/unknown review;
  atomic create/reconnect; current grant/Session execution and renewal; management
  routes with generated clients; deterministic focused tests.
- Non-goals: frontend implementation, production/live consent/deployment,
  multi-account modes, relay, per-task consent, automatic replay or paid scanner.
- Approved mechanisms: M1–M10, M12–M16; M11 API state/projection support only.
- Authority references: exact approved Design Authority and retained Toolkit,
  MCP OAuth, System Settings and canonical Session execution contracts.
- Design delta: None.
- Removal obligations: no existing provider/state removal; consolidate any new
  prototypes, expire/discard only unpublished local ciphertext; no remote revoke.
- Absence verification: no duplicate Google authority, no per-connection app
  secret copies, unrelated provider regression checks, generated-client diff.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Task policy and scanner | /root | `core/google_policy*`, `core/google_screening*`, Google config in `core/tools.py` | Approved M2/M14/M16 | Exact tools/scopes, bounded safe content | Malicious/benign/budget/partial-grant unit fixtures |
| Operator registration | /root | `core/google_system_setting*`, registry/Section, `services/google_application/**`, Admin routes | M13 | One current encrypted secret and redacted preparation | Rotation/configuration/redaction/optimistic tests |
| Lifecycle and persistence | /root | `core/google_oauth*`, Google models/repos, generated migration/revision | Policy/setting | Exact staged candidates, one current grant, idempotent outcome | Authority/publication/reconnect race tests |
| OAuth and management API | /root | `services/google_oauth/**`, public Google routes | Repository/provider SDK | Offline identity/grant evidence and safe review | Provider/service/route fixtures; OpenAPI/client generation |
| Execution | /root | `engine/tools/google*`, provider registry; runtime service/repo | Current grant/policy/scanner | Per-service snapshots and fenced effects | Cached grant loss, stale owner/refresh and blocked content tests |

- Integration order: pure policy/scanner/config; operator registration; models/
  completed repository operations; SDK service/routes; execution; migration/
  generated clients; focused plus integrated checks.
- Independent review: `/root/google-feature-reviewer`, requested by root only
  after all workstreams integrate and root validation stabilizes the diff.
- Final validation: root-owned Ruff/type checker/tests, migration graph and
  repository fixtures, OpenAPI/client generation, docs checks and PR CI.
- Scope-drift check: every change traces to assigned M IDs; reject added modes,
  token pooling, participant identity, permission inbox, blind replay and bypass.
- Context checkpoint: completed at `cdefeda1ad0fd255d1171a5228126b3ca33025cb`,
  PR #2252. Root corrected Boolean client decoding, explicit renewal consent,
  Admin secret-safe validation and migration enum ordering. The same independent
  reviewer approved the corrected phase under revision 4 M1–M16. Root backend
  12,299 passed/three Redis-only skips; migration 26, client templates 16 and
  documentation 18 passed. Latest-SHA CI 38448628646 succeeded, including required
  and Web E2E. Unmerged; no live provider or production change. Phase 2/3 remain.
