---
title: "Adopt testenv QA Fixture-First Architecture Historical Requirements Reconstruction"
created: 2026-05-12
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: testenv-260512
historical_reconstruction: true
migration_source: "docs/azents/adr/0029-testenv-qa-fixtures.md"
---

# Adopt testenv QA Fixture-First Architecture Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `testenv-260512`
- Source: `docs/azents/adr/testenv-260512-testenv-qa-fixtures.md`
- Historical source date basis: `2026-05-12`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

nointern `testenv/nointern/` is designed around `run-tc`, setup DAG, run-scoped state, and fresh-context verifier. This improved TC execution reliability, but recent QA showed that QA environment preparation cost and uncertainty are now larger problems than product runtime defects.

Representative symptoms:

- The agent re-evaluates environment readiness for user/workspace/agent/devserver/sandbox on every QA run.
- The verifier default depends on `claude -p`, so organization policy or subscription state can block QA itself.
- Narrow feature probes are tied to broad chat baseline, LLM, shell pipeline, and nested `run-tc`, obscuring the real failure cause.
- devserver state has no worktree fingerprint, so a run can attach to a devserver from another worktree.
- Existing setup state is tied to `runs/<run-id>/state.json`, making it unsuitable as the source of truth for long-lived QA environments.

The core goal of this decision is not preserving existing TCs. It is to **accurately set up and verify reusable fixture environments so agents do not waste time and tokens setting up and interpreting the QA environment every time**.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
