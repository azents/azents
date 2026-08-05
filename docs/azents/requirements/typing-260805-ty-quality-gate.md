---
title: "Unified Python Type Quality Gate Requirements"
created: 2026-08-05
updated: 2026-08-05
implemented: 2026-08-05
tags: [python, typing, ci, developer-experience]
document_role: primary
document_type: requirements
snapshot_id: typing-260805
---

# Unified Python Type Quality Gate Requirements

- Snapshot: `typing-260805`
- Document reference: `typing-260805/REQ`

## Problem

Azents maintains two Python type-checking paths for the backend application, which leaves contributors and CI with different configuration, command, and suppression conventions.

## Primary Actor

An Azents contributor changing Python code.

## Primary Scenario

A contributor changes a maintained Python project, runs the documented quality checks, and receives the same enforced type-quality result that CI applies without installing, configuring, or interpreting Pyright.

## Supporting Scenarios

- CI evaluates every maintained Python project through its existing quality workflow without a project-specific Pyright branch.
- Existing runtime behavior, formatting, linting, tests, and generated-contract checks remain protected by their current tools.

## Goals

- Provide one enforced Python type-quality gate for maintained code.
- Remove active Pyright configuration, dependencies, and execution paths.
- Keep contributor instructions aligned with CI.

## Non-Goals

- Replace Ruff linting or formatting with a type checker.
- Change application runtime behavior or external contracts.
- Rewrite executed database migrations or implemented historical documentation.

## Requirements

### REQ-1. One enforced Python type-quality gate

Maintained Python projects must use one documented and CI-enforced type-quality command.

**Acceptance criteria**

- The backend application and other maintained Python project CI entries use `ty check --error-on-warning` for type quality.
- Pre-commit runs the same type-quality command for relevant backend changes.
- No CI or pre-commit path executes Pyright.

### REQ-2. Remove active Pyright ownership

Contributors must not need active Pyright configuration, dependencies, or source directives to pass maintained quality gates.

**Acceptance criteria**

- Maintained configuration and dependency declarations contain no active Pyright setup.
- Current contributor documentation names `ty` as the Python type checker.
- Non-migration maintained Python source and tests contain no Pyright directive.

### REQ-3. Preserve other quality protections

The migration must not weaken unrelated quality gates or application behavior.

**Acceptance criteria**

- Ruff check/format, pytest, and backend OpenAPI drift verification remain configured.
- The backend `ty` check completes with zero diagnostics.
- The migration does not change runtime application behavior.

## Fixed Constraints

- `ty` is the replacement type checker.
- Ruff remains the lint/format tool; pytest remains the test tool.
- Executed Alembic migration files are immutable.
- Implemented Requirements, ADR, and Design documents are immutable historical records.

## Open Assumptions

- Existing `ty` configuration remains sufficient after stale Pyright-only directives are removed; any discovered `ty` diagnostic is fixed without restoring Pyright.

## Confirmation

Confirmed by the requester on 2026-08-05 through the direct instruction to remove Pyright settings and migrate CI and quality enforcement to `ty` in a stacked PR.
