---
title: "Toolkit Friendly Identifiers Implementation Plan"
created: 2026-10-01
updated: 2026-10-01
tags: [toolkit, backend, engine, frontend, database, migration, testing]
---

# Toolkit Friendly Identifiers Implementation Plan

- Requirements: [toolkit-261001/REQ](../requirements/toolkit-261001-friendly-identifiers.md)
- Decisions: [toolkit-261001/ADR](../adr/toolkit-261001-friendly-identifiers.md)
- Design: [toolkit-261001/DESIGN](../design/toolkit-261001-friendly-identifiers.md)
- Delivery shape: three stacked PRs
- Approved Design revision: `1`
- Approved Design mechanisms: `M1, M2, M3, M4, M5, M6, M7, M8`
- Design delta: `None`

## Delivery Stack

1. `toolkit friendly identifiers [1/3]: add Foundation namespace persistence`
   - Branch: `feature/toolkit-identifiers-1-foundation-data`
   - Base: `origin/main`
   - Adds namespace reservations and sequences, migration/backfill, transactional
     allocation and retirement, and write-path population while preserving current
     Name, Slug, duplicate-rejection, and runtime-prefix behavior.
2. `toolkit friendly identifiers [2/3]: cut over duplicate-safe runtime readers`
   - Branch: `feature/toolkit-identifiers-2-foundation-runtime`
   - Base: phase 1
   - Makes the persisted namespace relation mandatory for effective reads and carries
     stored Slug, effective namespace, ToolkitConfig Name, and safe source identity
     through Engine catalog construction, Tool Search, routing, hooks, events, and
     activity while retaining duplicate-write rejection and Slug unique indexes.
3. `toolkit friendly identifiers [3/3]: enable duplicate Slugs and friendly defaults`
   - Branch: `feature/toolkit-identifiers-3-capability`
   - Base: phase 2
   - Drops Slug unique indexes, removes conflict rejection, adds backend default
     materialization and Web placeholders, regenerates clients, proves duplicate MCP
     routing E2E, promotes current Specs, marks the snapshot implemented, and removes
     this plan family after validation.

All three PRs must be created before waiting on required CI. They are review and rollout
boundaries; they are not independent sources of product or Design authority.

## Ownership and Review

- Implementation and integration owner: `/root`; no implementation is delegated.
- Independent read-only reviewer: `/root/toolkit-identifiers-reviewer`.
- The same reviewer examines every root-integrated stable phase diff.
- The root agent owns every validation command, review-finding correction, re-review
  request, branch progression, PR creation, and CI follow-up.
- Review authority: confirmed Requirements, accepted ADR D1-D4, approved Design
  revision 1 and M1-M8, current Specs, repository conventions, and the phase contract.

## Workstreams and Interfaces

### Persistence and mutation authority

- Add durable Agent namespace reservations and per-base monotonic sequences.
- Backfill the complete `enabled_only=False` effective relation without rewriting
  ToolkitConfig Name, Slug, credentials, ownership, or settings.
- Populate, reuse, retire, and preserve reservations inside repository-owned
  transactions for Agent-owned create, shared attach, Slug update, detach/re-attach,
  disable/enable, Toolkit deletion, and Agent deletion.
- Retain current race-safe local/effective duplicate rejection through Foundation.

### Runtime source authority

- Join one active namespace reservation into every effective Toolkit projection.
- Carry base Slug and effective namespace as separate required fields.
- Prefix registered tools only with effective namespace.
- Keep ToolkitConfig ID as Session lifecycle identity.
- Make Tool Catalog source metadata authoritative for Tool Search, executor routing,
  hooks, durable source snapshots, and activity.
- Preserve auto-bound Toolkit behavior and historical event compatibility.

### Capability API and Web

- Materialize optional Name and Slug values in the backend from one deterministic policy.
- Share one versioned language-neutral conformance corpus with the TypeScript preview.
- Preserve omitted patch fields and use explicit blank Name/Slug fields for reset.
- Regenerate OpenAPI-derived Python and TypeScript public clients.
- Present Type, Name, Slug in dependency order with untouched local placeholders.
- Permit duplicate stored Slugs only after every runtime reader is namespace-aware.

### Verification and specification

- Extend the existing deterministic MCP fixture to distinguish same-Slug instances.
- Add migration, repository concurrency, service, Engine, Tool Search, hook, event,
  frontend interaction, generated-contract, and required E2E coverage.
- Validate Foundation relation/reservation parity and Capability duplicate routing.
- Update the Toolkit and affected execution-flow Living Specs only after implementation
  behavior is stable.

## Dependencies and Integration Boundaries

1. Phase 1 establishes schema and mutation invariants before any reader depends on them.
2. Phase 2 consumes only phase-1-populated namespace state and leaves all current write
   restrictions active.
3. Phase 3 may remove restrictions only after phase 2 has no runtime Slug-prefix or
   registered prefix-parsing authority.
4. Public API source schemas change before generated clients; generated files are never
   edited manually.
5. The existing Web form remains explicit-value-based until Capability API compatibility
   is complete; production deployment order remains API before Web.
6. No phase performs a live deployment, database operation, or PR merge.

## Context Checkpoints

- Phase 1 checkpoint: schema exists, backfill is deterministic, every relation-creating
  mutation owns allocation, current duplicate behavior remains unchanged, and runtime
  still uses stored Slug.
- Phase 2 checkpoint: every registered runtime reader uses namespace authority, all
  source consumers agree on Toolkit identity, missing authority fails closed, and
  current writes still reject duplicate Slugs.
- Phase 3 checkpoint: defaults and placeholders are consistent, duplicates persist and
  execute safely, obsolete conflict paths and indexes are absent, E2E and quality checks
  pass, Specs describe current behavior, and temporary plans are removed.

## Removal Obligations and Absence Evidence

- Capability removes the two ToolkitConfig Slug unique indexes.
- Capability removes `DuplicateSlug`, `EffectiveSlugConflict`, effective conflict
  queries, and duplicate effective Slug assertions after their Foundation purpose ends.
- Foundation runtime removes stored Slug as the registered final-prefix authority and
  removes prefix parsing as registered Toolkit source authority.
- Capability removes create-form Name/Slug prefilling and required create request fields.
- Capability replaces tests that assert Slug conflicts with duplicate success and routing
  evidence while retaining Foundation compatibility coverage where relevant.
- Final spec promotion removes statements that stored Slug is locally or effectively
  unique.
- Absence evidence uses schema inspection, repository-wide symbol searches, OpenAPI and
  generated-client diffs, catalog/source tests, required E2E, and `/spec-review`.

## Validation Matrix

- Python persistence: migration upgrade/backfill/downgrade guards; repository and
  transaction tests; Ruff; formatter; configured type checker.
- Python runtime: resolve, catalog, Tool Search, hooks, events, executor, Session Toolkit
  lifecycle, and worker tests; Ruff; formatter; configured type checker.
- TypeScript: shared conformance tests, form/container/component/Storybook tests,
  tRPC contract tests, format, lint, typecheck, and Web build.
- Contracts: Public OpenAPI dump and Python/TypeScript client regeneration.
- E2E: required Public API and saved-Agent Web cases using deterministic MCP instances,
  duplicate shared/owned combinations, lifecycle reuse, Slug change, deletion no-reuse,
  Tool Search execution, and unaffected unique final names.
- Specs: `/spec-review`, current Toolkit and affected flow updates, shared implemented
  date on Requirements and Design.

## Rollout, External Actions, Risks, and Blockers

- Foundation persistence and Foundation runtime are independently reviewable and
  deployable in order.
- Capability schema removal precedes duplicate writes; older Foundation writers may
  reject but cannot corrupt a mixed rollout.
- Capability Web placeholder deployment follows complete Capability API adoption.
- After duplicates exist, rollback is limited to Foundation-compatible code on the
  forward schema.
- Highest risks are migration backfill completeness, multi-Agent Slug-update locking,
  hidden stored-Slug consumers, generated-client drift, and tests that prove declaration
  uniqueness without proving handler routing.
- No current blocker or Design delta is known.

## Plan Cleanup

The phase-3 branch removes this implementation plan and all Toolkit-friendly identifier
phase plans after implementation, integrated validation, independent review, spec
promotion, and snapshot implementation marking are complete.
