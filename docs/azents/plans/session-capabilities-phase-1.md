---
title: "Repository Session Capabilities First PR Execution Plan"
created: 2026-10-04
tags: [repository, session-capabilities, implementation-plan]
---

# Phase Execution Plan

- Phase: foundation and mechanical repository migration.
- Branch/base: `refactor/read-write-session-repositories-261004` to `main`.
- Inputs: requester-approved foundation sample and private backing correction.
- Deliverable: every repository/caller/test uses explicit session capabilities.
- Interfaces: `ReadSession`, `WriteSession`, private concrete wrappers and factories.
- Approved mechanisms: `sessioncaps-261004/DESIGN` M1–M3.
- Authority: `sessioncaps-261004/REQ-1`–`REQ-3`, ADR D1–D3.
- Design delta: None.
- Non-goals: lock removal, prompt changes, MCP cadence changes, deployment.

## Ownership

- Root: foundation, DI, documentation, integration, commits, PR and validation.
- `sessions-repo-runtime`: runtime and Agent Runtime repositories.
- `sessions-repo-external`: external/identity/workspace/OAuth repositories.
- `sessions-repo-memory`: memory, catalog and source metadata repositories.
- `sessions-repo-core`: remaining repositories, VFS/state generics and owner adapter.
- `sessions-caller-runtime`: Runtime-related services.
- `sessions-caller-other`: remaining production callers and factories.
- `sessions-test-repair-repos-luna`: repository tests and persistence test helper repair.
- `sessions-test-repair-other-luna`: other tests and shared fixtures.
- Mechanical test repair explicitly uses Luna; Terra is excluded. The earlier
  implementation lanes have handed their changes to the root agent.
- Exact non-overlapping path manifests are maintained in the execution Session.
- Independent reviewer: `/root/catalog-design-owner`; root requests stable integrated review.

## Integration and Validation

Freeze foundation first, then migrate parallel lanes. Repository collaborators
receive wrappers, while SQLAlchemy infrastructure uses explicit raw attributes.
Root owns whole-backend lint/type/tests and required CI/E2E. Subagents run focused
checks on their own paths and report cross-lane requirements.

Removal obligations: raw repository session contracts, incompatible captured
session/generic assumptions and raw-yielding migrated factories. Absence checks
must distinguish legitimate raw infrastructure from repository boundary leaks.
Do not replace raw contracts with casts, broad unions or forwarding shims.

At integration, compare SQL/lock/transaction semantics and reject unrelated
optimizations. Keep the current lock-removal phases queued separately. Record
changed interfaces, validation evidence and remaining scope at phase completion.
