---
title: "GPT apply-patch Validation Report"
created: 2026-07-20
tags: [engine, runtime, testenv, validation]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/gpt-apply-patch-testenv-report-2026-07-20.md"
---

# GPT apply-patch Validation Report

## Status

The required credential-free CI matrix passed on PR #656 in CI run `29742272333`, including deterministic, runtime-provider, and web-surface E2E lanes. The runtime-provider lane executed the new scenario through a real Docker Runtime Provider and Runtime Runner. Local container execution remained unavailable because this agent runtime does not expose a Docker daemon socket.

## Validated Scope

The implementation validation covers:

- strict Add, Update, and Delete parsing and execution;
- path confinement, symlink and file-kind rejection, newline handling, resource limits, staging, revalidation, deterministic commit ordering, and exact partial-failure reporting;
- ordered Runtime cancellation, pending and active Runner cancellation, and typed terminal settlement;
- GPT-only client tool profile resolution and catalog projection before Tool Search, declaration budgeting, lowering, and executor freezing;
- ordinary completed JSON function-call execution with unchanged `edit` behavior;
- Engine success and failure rendering without repeating raw patch, source, or replacement content;
- a deterministic E2E flow through the public API, AIMock, Engine Worker, Runtime Control, Docker Runtime Provider, and real Runtime Runner.

## Deterministic E2E Scenario

The runtime-provider E2E scenario uses the existing credential-free `deterministic-success` model listing. Its selected model snapshot is `gpt-5.5` with developer `openai` and family `gpt-5.5`.

The scenario:

1. creates a shell-enabled agent through public APIs;
2. starts a real Runtime Runner;
3. prepares a portable workspace with `exec_command`;
4. emits one completed `apply_patch` call that updates, adds, and deletes files;
5. verifies typed durable result metadata and the final filesystem manifest with a separate Runner command;
6. emits a traversal patch using `../apply-patch-escaped.txt`;
7. verifies a parse-phase `invalid_path_component` failure, no external file creation, unchanged committed files, one terminal result, and an idle live session projection.

The scenario also verifies that success and failure result text do not repeat replacement markers from the raw patch.

## Evidence

| Area | Command or evidence | Result |
| --- | --- | --- |
| Runtime control library | `uv run ruff check --fix . && uv run ruff format . && uv run pyright && uv run pytest -q` | Passed: 36 tests |
| Runtime Runner | `uv run ruff check --fix . && uv run ruff format . && uv run pyright && uv run pytest -q` | Passed: 98 tests |
| Backend complete stack | `uv run ruff check --fix . && uv run ruff format . && uv run pyright && uv run pytest -q` | Passed: 1852 tests, 437 skipped |
| E2E static validation | `uv run ruff check --fix . && uv run ruff format . && uv run pyright .` | Passed |
| E2E collection | focused `pytest --collect-only` for the apply-patch runtime-provider test | Passed: 1 test collected |
| E2E local execution | focused real-Runner pytest invocation | Environment-blocked before fixture setup: Docker socket not present |
| E2E CI execution | CI run `29742272333` on PR #656 | Passed: deterministic, runtime-provider, and web-surface E2E lanes |

## Fixture and Credential Policy

No direct database writes or new setup scripts are used. The scenario creates product state through public/admin API boundaries and reuses the existing AIMock and Docker Runtime Provider fixtures.

No production-accessible fault injection was added. Later-commit failure remains deterministically covered through the Runner's injected test boundary, while the E2E scenario exercises the production Runner configuration.

Optional OpenAI API-key and ChatGPT OAuth live evaluations were not run because no live prerequisite snapshot or credentialed workflow was prepared for this validation environment. Required acceptance remains credential-free and deterministic.

## Spec Promotion Input

Phase 7 must update:

- `agent-execution-loop.md` for selected-model client tool profile projection, completed function-call admission, typed patch result metadata, and commit-sensitive cancellation settlement;
- `agent-runtime-control.md` for `file.apply_patch`, strict V4A semantics, path and file safety, staging and revalidation, ordered commit, typed terminal success/failure, and no-rollback partial failure;
- both specs' `code_paths`, `last_verified_at`, and changelog/version records as required by the existing spec format.

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-230) remains unchanged.
