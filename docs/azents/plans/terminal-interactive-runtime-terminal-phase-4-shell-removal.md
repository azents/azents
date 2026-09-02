---
title: "Interactive Runtime Terminal Phase 4 Shell Removal Plan"
created: 2026-09-01
tags: [terminal, runtime, migration, implementation, stacked-prs]
---

# Interactive Runtime Terminal Phase 4 Shell Removal Plan

## Phase Execution Plan

- Phase: `4/5 shell_enabled cutover`
- Branch/base: `feature/terminal-260901-shell-removal` → `feature/terminal-260901-web` / PR #1605
- PR boundary: remove the obsolete Agent `shell_enabled` product setting, make managed Runtime capability the sole Agent Runtime Toolkit gate, and drop the durable column.
- Inputs: Phase 3 Terminal UI and independent Terminal policy are committed and exposed through generated clients.
- Deliverables: no active source, schema, API, generated client, Web form, seed, or test contract depends on `shell_enabled`; managed Runtime Agents retain existing Runtime Toolkit capabilities; Runtime-free/removing Agents retain none; a generated migration drops the column and downgrade recreates it as non-null `true`.
- Non-goals: Terminal E2E execution, Living Spec promotion, snapshot implementation markers, and feature-plan cleanup remain Phase 5.
- Interfaces: `RuntimeCapabilitySnapshot` and `RuntimeCapabilityDefinition` no longer carry Shell gates; Agent create/update/read contracts no longer expose `shell_enabled`; Runtime add/remove/finalizer transitions no longer write it; `terminal_enabled` remains browser-Terminal policy only.
- Approved Design mechanisms: `M11`, `M12`
- Authority references: `terminal-260901/REQ-8`, `terminal-260901/ADR-D4`, `terminal-260901/ADR-D6`, `terminal-260901/DESIGN` revision `1`
- Design delta: `None`
- Removal obligations: Agent RDB/repository/service/API fields; Runtime capability snapshot/definition/resolution gates; Worker Toolkit binding; Runtime add/remove/finalizer writes and waits; OpenAPI and generated Python/TypeScript clients; Main Web forms/summaries/schemas/tRPC/stories/localization; testenv seed and active test fixtures.
- Absence verification: bounded `shell_enabled` inventory must be empty across active source, OpenAPI, generated clients, Main/Admin Web, testenv seed, and current tests. Historical migrations and immutable Requirements/ADR/Design remain; current Living Specs are updated and verified in Phase 5.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Capability and lifecycle cutover | `/root` | `python/apps/azents/src/azents/core/runtime_capabilities.py`, Worker executor, Runtime transition/removal/finalizer services and focused tests | managed Runtime authority | Runtime Toolkit availability depends only on managed capability; no lifecycle path writes Shell state | Ruff, ty, focused pytest, static inventory |
| Agent persistence, API, migration, and clients | `/root` | Agent RDB/repository/service/Public API, `db-schemas/rdb`, Public OpenAPI, generated Python/TypeScript clients | capability cutover | removed field contracts plus generated linear drop migration with downgrade default `true` | migration tests, API/repository/service tests, deterministic OpenAPI/client generation |
| Web and fixture removal | `/root` | Main Web Agent settings/forms/tRPC/stories/locales and `testenv/azents` seed/required fixture callers | generated Public client | no Shell setting UI or fixture argument remains | Web format/lint/typecheck/tests/build/Storybook; testenv Ruff/ty/tests; static inventory |

- Integration order: cut over capability resolution → remove lifecycle writes → remove Agent persistence/service/API field → generate migration and clients → remove Web and fixture consumers → run bounded absence inventory and full affected validation.
- Independent review: `/root/terminal-reviewer` reviews the stable diff read-only against REQ-8, ADR-D4/D6, Design M11/M12, this phase contract, migration rollback behavior, managed-versus-runtime-free capability semantics, generated surfaces, and absence evidence.
- Final validation: Azents Ruff/format/ty and affected pytest suites; migration upgrade/downgrade/schema tests; deterministic OpenAPI dump; Python/TypeScript Public client generation and checks; Web format/lint/typecheck/tests/build/Storybook; testenv Ruff/format/ty and affected tests; `git diff --check`; bounded `shell_enabled` grep excluding immutable history, historical migrations, active feature plans, and Phase-5-owned Specs.
- Scope-drift check: preserve independent `terminal_enabled`; preserve all managed Runtime Toolkit capabilities; do not add compatibility fallbacks or retain dormant Shell fields; do not edit historical migrations or Phase-5 Specs.
- Context checkpoint: Phase 3 PR #1605 is the exact base. Current active inventory contains 171 `shell_enabled` references across Agent contracts, capability/lifecycle code, generated clients, Web, testenv, and tests; one historical introduction migration and two current Specs remain outside the Phase 4 absence boundary as explicitly assigned history/Phase-5 work. Current blockers: none.
