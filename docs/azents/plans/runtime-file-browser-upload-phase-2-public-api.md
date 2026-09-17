---
title: "Runtime File Browser Upload Phase 2 Public API"
created: 2026-09-17
updated: 2026-09-17
tags: [runtime, files, api, implementation, phase-plan]
---

# Runtime File Browser Upload Phase 2 Public API

## Phase Execution Plan

- Phase: `2/3 — Public JSON API and generated clients`
- Branch/base: `feat/upload-260917-2-public-api` → `feat/upload-260917-1-runtime-backend`
- PR boundary: `Expose the approved Agent Workspace upload control plane without proxying file bytes`
- Inputs: `Phase 1/3 complete; approved fileupload-260917/DESIGN revision 1`
- Deliverables: `Agent-scoped create/finalize/status/cancel/retry services and routes; public-safe upload ticket/status/error/conflict models; API-to-Runtime-Control metadata client composition; OpenAPI dump; generated Python/TypeScript clients; authorization and route tests`
- Non-goals: `Binary content route, Main Web body proxy, FileBrowser UI, browser hashing/direct PUT implementation, E2E, new Runtime mechanism, Exchange fallback`
- Interfaces: `Stable upload_id routes; create response containing one presigned upload ticket and required headers; finalize revision; public phase/error unions; cancel/retry/conflict request; generated SDK functions`
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M8, M11, M12, M14`
- Authority references: `fileupload-260917/REQ-1` through `REQ-6`; `fileupload-260917/ADR-D1` through `D5`, `D8`, `D9`; Phase 1 internal interfaces`
- Design delta: `None`
- Removal obligations: `Do not carry forward the obsolete application/octet-stream content route, Main Web binary proxy contract, or source-upload streaming client from upload-260917`
- Absence verification: `OpenAPI and generated clients contain only JSON control operations; repository search finds no Workspace upload content route, body iterator, or handwritten duplicate backend contract`

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Public domain and service | Root agent | `python/apps/azents/src/azents/services/chat/workspace_upload*`, Workspace service tests | Phase 1 coordinator | Authorization, concealment, destination validation, public mapping | Service unit tests, Ruff/type |
| JSON routes and schemas | Root agent | `python/apps/azents/src/azents/api/public/chat/v1/**` | Public service | Create/finalize/status/cancel/retry routes and bounded public models | Route/schema/error tests |
| Runtime Control client composition | Root agent | API DI/dependencies/config and internal client adapter | Phase 1 metadata client | API replicas call Runtime Control authority and never own upload state/body | Composition and transport failure tests |
| OpenAPI and generated clients | Root agent | OpenAPI dump, Python public client, `typescript/packages/azents-public-client` | Stable routes | Generated typed control operations and unions | Generation/diff/client tests |
| Integrated absence and validation | Root agent | All phase paths | All workstreams | Frozen Phase 2 diff | Full phase checks and absence search |

- Integration order: `public models/service → Runtime Control metadata adapter → JSON routes → OpenAPI dump → generated clients → integrated absence and validation`
- Independent review: `fileupload-reviewer; root requests read-only review after integrated validation and frozen diff`
- Final validation: `OpenAPI generation/check; Python Ruff/format/type/Pytest; generated Python/TypeScript client checks; auth/concealment/conflict route tests; no-content-route search; docs validation; git diff --check`
- Scope-drift check: `Only M1/M2/M3/M4/M5/M8/M11/M12/M14; no Web UI, file body transport, Runtime state change, new deployment mode, or fallback`
- Context checkpoint: `Record public route paths, generated operation names, ticket/header and status/error contracts, validation/review evidence, absence proof, remaining Web/E2E scope, and Design delta None`
