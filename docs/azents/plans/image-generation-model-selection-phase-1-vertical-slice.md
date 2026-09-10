---
title: "Image Generation Model Selection Phase 1"
created: 2026-09-10
updated: 2026-09-10
tags: [agent, workspace, image-generation, model-catalog, implementation]
---

# Image Generation Model Selection Phase 1

## Phase Execution Plan

- Phase: `1/1 Full vertical slice`
- Branch/base: `feat/image-generation-model-selection` → `origin/main`
- PR boundary: complete image-generation model selection behavior
- Inputs: confirmed `image-260910/REQ`, accepted `image-260910/ADR-D1` through
  `image-260910/ADR-D10`, approved `image-260910/DESIGN` revision 2
- Deliverables: stored image catalog, default and explicit settings, validation,
  provider dispatch, localized UI, generated clients, Specs, and deterministic evidence
- Non-goals: image quality/size controls, independent image provider, ChatGPT OAuth or
  xAI explicit model choice, generated-image pipeline changes
- Interfaces: Design sections M1-M11
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11`
- Authority references: `image-260910/REQ-1` through `REQ-5`,
  `image-260910/ADR-D1` through `ADR-D10`, current Agent, Model Catalog, Toolkit, and
  Agent Execution Loop Specs
- Design delta: `None`
- Removal obligations: static frontend registry, manual unavailable flag, name-only
  built-in config serialization, local Storybook absolute path, stale explicit runtime
  acceptance
- Absence verification: grep and diff checks plus mapping, component, repository, and
  provider-proxy tests

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Schema and repositories | `/root` | backend enums, RDB catalog/integration models, migration, catalog repositories | approved Design | purpose/version/image entry persistence | migration and repository tests |
| Catalog service and API | `implementation-catalog` | model listing, image registry/service, integration routes/data | schema contract | stored read/sync contract | service and route tests |
| Settings and runtime | `/root` | built-in config, model option normalization, Agent/Workspace services, run resolution | catalog read authority | canonical save and pre-dispatch validation | focused backend tests |
| Generated clients and UI | `/root` | public OpenAPI/clients, web container/component/form/i18n/stories | API and settings contract | catalog-driven UI | format/lint/typecheck/unit/story tests |
| E2E and Specs | `/root` | testenv fixtures/tests and current Living Specs | complete vertical behavior | deterministic acceptance evidence and current behavior docs | required focused E2E and spec review |

- Integration order: schema → repositories → registry/sync/read API → settings validation
  → runtime defense → generated clients → UI → E2E → Specs → cleanup
- Independent review: `implementation-reviewer`; read-only review against Requirements,
  ADR, Design revision 2, M1-M11, removal obligations, security, data integrity,
  interfaces, conventions, and verification evidence
- Final validation: relevant Python Ruff/type/test, migration/schema checks, OpenAPI
  generation, relevant TypeScript format/lint/typecheck/test/build, deterministic E2E,
  spec review, clean diff, and CI
- Scope-drift check: every diff hunk must trace to M1-M11 or a required generated/spec
  consequence; quality/size controls and new providers remain absent
- Context checkpoint: design is approved, current prototype is untrusted except for its
  UI shell, and no implementation blocker remains
- Completion checkpoint: M1-M11 are implemented with `Design delta: None`; backend,
  generated-client, frontend, production-build, deterministic E2E, Living Spec,
  generated-index, and clean-diff validation passed. Independent review found and
  verified corrections for credential-generation fencing and runtime capability
  revalidation, with no remaining blocking findings.
