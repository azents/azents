---
title: "Subagent Removal Design"
created: 2026-07-06
updated: 2026-07-06
tags: [backend, frontend, api, engine, documentation]
---
# Subagent Removal Design

## Summary

Azents will remove the existing subagent implementation and related product surfaces so a future subagent redesign can start from a clean slate. The current implementation is tightly coupled to agent roles, toolkit inheritance, transcript events, public API schemas, generated clients, and frontend projections. Removing those surfaces reduces confusion before introducing the next design.

## Context

The current subagent model exposes subagents as specialized agents linked through an `agent_subagents` junction table. Parent agents receive a generated `subagent` tool that invokes the child agent and projects `subagent_start` / `subagent_end` events into the parent transcript.

This model is no longer the desired foundation. The next subagent direction should not inherit the old role/linking/event contract by accident. Existing deployments used for this cleanup do not require preserving subagent data.

## Goals

- Remove the current subagent runtime/tool implementation.
- Remove the agent-subagent link repository, service, API routes, schemas, and database model.
- Remove public API and generated-client surfaces for subagent links.
- Remove frontend subagent management and transcript rendering surfaces.
- Remove current living specs that describe subagent behavior.
- Preserve historical ADRs and unrelated design records unless they are dedicated obsolete implementation notes.

## Non-goals

- Design or implement the next subagent architecture.
- Preserve compatibility for existing subagent API clients.
- Preserve subagent table data.
- Rewrite adopted ADR history.

## Current Surface Area

### Backend domain and runtime

The existing implementation spans:

- `azents.engine.tools.subagent`
- `azents.repos.agent_subagent`
- `azents.services.agent_subagent`
- `azents.rdb.models.agent_subagent`
- `resolve_subagent_tools()` in run resolution
- worker/executor injection of the generated subagent tool
- `subagent_start` and `subagent_end` event builders/types/projections

### Agent schema

Subagent support also extended the general agent model with:

- `AgentRole.SUBAGENT`
- `toolkit_inherit_mode`
- subagent-oriented descriptions for shell and memory settings

The cleanup should remove `AgentRole.SUBAGENT` and `toolkit_inherit_mode`. Shell and memory settings should be retained only if they still represent normal agent behavior outside the subagent feature.

### Public API and generated clients

Subagent management is exposed through public agent routes and generated clients. Removing routes requires regenerating OpenAPI clients instead of manually editing generated client code.

### Frontend

The web app includes subagent management, workspace team cards, transcript blocks, detail modals, tRPC router wiring, and localized strings. These should be removed with the generated-client changes.

### Specs and documents

The living spec should no longer describe removed current behavior. Historical ADRs remain append-only. Dedicated subagent design and implementation report documents may be removed when they are obsolete and likely to confuse the redesign.

## Decisions

### D1. Remove instead of refactor

The old implementation will be deleted rather than hidden or partially retained.

Rationale: the next design should not inherit old API, DB, runtime event, or frontend semantics accidentally.

### D2. Do not maintain compatibility

The public subagent link API, generated client models, frontend routes, and event kinds will be removed without compatibility shims.

Rationale: this cleanup is explicitly a reset. Backward compatibility would preserve the conceptual coupling the cleanup is intended to remove.

### D3. Preserve ADR history

Adopted ADRs will not be rewritten or deleted. Current behavior documents under `docs/azents/spec/` will be updated or removed.

Rationale: ADRs are append-only decision history; living specs are the source of current behavior.

### D4. Regenerate generated clients

Generated public clients will be refreshed from the updated OpenAPI schema.

Rationale: generated artifacts must stay aligned with the API schema and should not be edited by hand.

## Planned PR Stack

1. **Design**: add this design record.
2. **Backend/API cleanup**: remove backend subagent runtime, repository/service/model/API surfaces, database schema references, and regenerate public clients.
3. **Frontend/spec cleanup**: remove web subagent UI/projections/tRPC wiring, testenv seeds, and current living specs for removed behavior.

## Backend Cleanup Plan

- Delete `engine/tools/subagent.py` and its tests.
- Delete `repos/agent_subagent`, `services/agent_subagent`, and the RDB model.
- Remove subagent event kinds and builders.
- Remove subagent route handlers and API data models.
- Remove `toolkit_inherit_mode` from agent repository/service/API schemas.
- Remove `AgentRole.SUBAGENT`; keep the agent role field only if still useful as a single-valued `agent` contract, otherwise collapse it from public schemas.
- Update tests that previously asserted subagent inheritance, subagent transcript projection, or subagent tool injection.
- Regenerate OpenAPI public clients.

## Database Cleanup Plan

Because preserving subagent data is not required, the final schema should not include:

- `agent_subagents`
- `agent_role` values for subagents
- `agents.toolkit_inherit_mode`
- subagent-specific enum values in event/session related database types

If migration history has already been applied in shared environments, create a new Alembic revision to drop these surfaces. If this branch is still before shared migration execution, migration history may be simplified only with explicit confirmation.

## Frontend Cleanup Plan

- Delete subagent management sections and storybook stories.
- Delete transcript subagent block/detail modal handling.
- Remove the `agentSubagent` tRPC router.
- Remove subagent fields from agent form/list types and schemas.
- Remove localized subagent strings.
- Update workspace home cards and stats to show only normal agent concepts.

## Spec Cleanup Plan

- Delete `docs/azents/spec/flow/subagent-delegation.md`.
- Remove subagent role/link/runtime behavior from agent, toolkit, conversation, workspace, and execution-loop specs.
- Regenerate documentation indexes after spec changes.

## Test Strategy

### Backend validation

- Run Ruff for backend changes.
- Run Pyright for backend changes.
- Run backend tests, with focused runs for agent service/API, engine run resolution, worker executor, and event projection tests.
- Dump OpenAPI after route/schema removal.

### Frontend validation

- Run TypeScript format, lint, typecheck, and build for the web workspace.
- Validate Storybook references do not import removed subagent components.

### E2E and fixture validation

No new user-facing subagent behavior is introduced. E2E coverage should focus on regression for normal agent creation/list/chat flows after subagent UI removal. Testenv seed validation should ensure default workspaces still seed normal agents without subagent fixtures.

### Evidence

Each implementation PR should record the commands run in the PR body. CI should be monitored only after all stacked PRs are created.

## Risks

- Generated client regeneration may surface additional TypeScript call sites that still expect subagent schemas.
- Removing event kinds can break old transcript replay if old events remain in local data. This is acceptable for the reset but should be explicit in release notes if needed.
- Migration cleanup depends on whether existing migration history has been applied in shared environments.

## Future Work

A separate design should define the new subagent architecture using the standalone Codex research note as context:

- `/workspace/agent/codex-subagent-research-2026-07-06.md`
