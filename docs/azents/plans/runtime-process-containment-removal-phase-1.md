---
title: "Runtime Process Containment Removal Phase 1"
created: 2026-08-11
tags: [runtime, security, implementation]
---

## Phase Execution Plan

- Phase: `1 - cohesive containment removal`
- Branch/base: `refactor/remove-runtime-process-containment` → `main`
- PR boundary: Remove the unsupported process-containment contract and restore minimum-privilege direct runtime workloads.
- Inputs: Confirmed `runtime-260811/REQ`, accepted `runtime-260811/ADR`, approved `runtime-260811/DESIGN` revision 1.
- Deliverables: Direct-only Profile/Runner/Provider behavior, null-only stored compatibility, synchronized deployment/API/client/spec surfaces, and validated absence of active containment code.
- Non-goals: User filesystem restriction, MITM proxy/network enforcement, live cluster changes, operator node-security changes.
- Interfaces: Existing direct and DinD runtime operations remain; active non-null containment documents fail closed; old null keys normalize away.
- Approved Design mechanisms: `M1`, `M2`, `M3`, `M4`, `M5`, `M6`, `M7`
- Authority references: `runtime-260811/REQ-1..6`, `runtime-260811/ADR-D1..D6`, current Runtime Provider/Control/Toolkit/Agent Runtime specs.
- Design delta: `None`
- Removal obligations: All entries in `runtime-260811/DESIGN` Removal and Replacement table.
- Absence verification: Repository grep, generated-schema inspection, workload render tests, Runner image checks, and focused regression tests.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Core/Profile/API | primary agent | `python/apps/azents`, generated API inputs | approved snapshot | removed containment contracts with null compatibility | focused pytest, OpenAPI dump |
| Runner | primary agent | `python/apps/azents-runtime-runner`, runtime-control library | Core contract | direct execution only | Ruff, ty, pytest, Dockerfile inspection |
| Providers/deployment | primary agent | Docker/Kubernetes providers, Helm, CI, testenv | Runner contract | minimum-privilege direct workloads | provider tests, chart render tests, testenv tests |
| Clients/UI/specs | primary agent | generated clients, admin web, living specs | OpenAPI and provider outputs | synchronized public surfaces | generation, TypeScript checks, spec review |

- Integration order: Core/Profile → Runner → Providers → Helm/CI/E2E → OpenAPI/clients/UI/specs → full validation.
- Independent review: `/code-review` on the stable final diff for Requirements/Design compliance, security/data-loss risk, compatibility, and stale references.
- Final validation: affected Python Ruff/ty/pytest; Helm tests; TypeScript format/lint/typecheck/build; OpenAPI/client generation; repository grep.
- Scope-drift check: all M2/M3/M4 removal and compatibility obligations implemented; no filesystem/network mechanism added; no direct-execution security claim introduced.
- Context checkpoint: documentation approved; code removal pending; no known blocker; live infrastructure remains untouched.
