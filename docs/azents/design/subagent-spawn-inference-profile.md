---
title: "Subagent Spawn Inference Profile Design"
created: 2026-07-11
updated: 2026-07-11
tags: [agent, backend, engine, subagent]
---

# Subagent Spawn Inference Profile Design

## Problem

Azents subagents currently inherit the complete effective inference profile of the concrete parent `AgentRun`. This is the correct default, but `spawn_agent` cannot assign a different Agent-owned model target or reasoning effort to a bounded delegated task.

The feature must add an explicit override without introducing physical model identifiers, Agent-default fallback, partial child creation, or a separate long-term model lifecycle for child sessions.

## Goals

- Preserve exact parent-run profile inheritance when no override is supplied.
- Allow a default subagent to select an Agent-owned model target and reasoning effort at spawn time.
- Reuse existing model-target resolution, reasoning capability validation, and effort normalization.
- Preserve durable run provenance and restart-safe first-run activation.
- Keep later child runs on normal session-last-used profile semantics.
- Follow Codex full-history fork restrictions.

## Non-goals

- Predefined or specialist subagent profiles.
- Model, effort, or service-tier settings owned by an `agent_type`.
- Per-`followup_task` inference profile overrides.
- Raw provider/model selection in collaboration tools.
- A user-facing Subagent profile configuration UI.
- Permanently pinning a child session to one resolved physical model.

## Current behavior

`spawn_agent` receives `name`, `task`, optional `agent_type = default`, and optional `fork_turns`. The tool validates the current parent run, creates the child participant and hidden child session, and precreates the first child `AgentRun` with:

- the parent run's requested model target label;
- the parent run's requested reasoning effort;
- the parent run's resolved model snapshot and resolved effort;
- the parent run's effective context window and compaction threshold;
- `inference_profile_source = parent_run`;
- `parent_agent_run_id` pointing to the concrete spawning run.

The child session's last-used requested label and effort are initialized before the wake-up is published.

## Proposed contract

Extend the model-visible `spawn_agent` input with two optional fields:

```json
{
  "name": "research",
  "task": "Investigate the provider behavior",
  "agent_type": "default",
  "fork_turns": "3",
  "model_target_label": "fast",
  "reasoning_effort": "low"
}
```

`model_target_label` is an Agent-owned label. The tool never accepts an integration id, provider, physical model identifier, model snapshot, or catalog entry.

`reasoning_effort` uses the existing normalized `ModelReasoningEffort` enum.

The generated tool description identifies the available target labels and their supported explicit efforts from the current Agent snapshot. It never identifies the provider, physical model identifier, model display name, resolved snapshot, or catalog metadata behind a label. Backend validation remains authoritative.

## Model-visible prompting

Match Codex V2's placement, strength, and phrasing as closely as Azents terminology permits. Keep inference-profile guidance in the dynamic `spawn_agent` tool description and field descriptions rather than expanding the general collaboration static prompt.

Use this inheritance guidance, adapted only for the Azents target abstraction:

```text
Spawned agents inherit the current parent Run's model target by default.
Omit `model_target_label` to use that preferred default; set
`model_target_label` only when an explicit override is needed.
```

Do not add the stronger Codex V1 requirement that the user must explicitly request another model or that the model must state a clear task-specific reason. Codex V2 frames inheritance as preferred and override as exceptional without adding that authorization threshold.

List every Agent-owned target because the list is already curated and capped at ten entries. Follow the Codex V2 dynamic-list shape while exposing labels rather than physical models:

```text
Available model target overrides
(optional; inherited parent Run target is preferred):
- `fast` Reasoning efforts: low, medium, high.
- `quality` Reasoning efforts: medium, high, xhigh.
```

The list contains only labels and their model-visible effort contract. It does not include actual model names, display names, providers, developers, families, context limits, pricing, integration identities, or routing snapshots.

Use concise field guidance parallel to Codex V2:

- `model_target_label`: `Model target label override for the new agent. Omit unless an explicit override is needed. Full-history forks inherit the parent Run profile.`
- `reasoning_effort`: `Reasoning effort override for the new agent. Omit to inherit or normalize from the parent Run's effective effort. Full-history forks inherit the parent Run profile.`

Keep the existing Codex V2-style guidance that `spawn_agent` is for a concrete, bounded subtask that can run independently. Do not add generic guidance encouraging cheaper, smaller, or faster model targets. Invalid labels, efforts, and full-history combinations remain backend validation errors.

## Profile derivation

The concrete parent `AgentRun`, not the Agent default, is the base profile.

| Model target input | Effort input | Result |
|---|---|---|
| omitted | omitted | Copy the parent run's requested profile, resolved snapshot, resolved effort, and effective limits. |
| explicit | omitted | Resolve the explicit target and normalize from the parent run's resolved effort. |
| omitted | explicit | Keep the parent resolved model snapshot and validate the explicit effort against it. |
| explicit | explicit | Resolve the explicit target and validate the explicit effort exactly. |

### Automatic effort transition

For a model-only override, use the parent run's `resolved_reasoning_effort` as the baseline. A null baseline becomes `medium`.

Given the target model's canonical ordered effort levels:

1. preserve the baseline when supported;
2. otherwise choose the greatest supported effort below it;
3. otherwise choose the smallest supported effort;
4. return null when the target advertises no explicit effort levels.

An explicit effort is never silently normalized. It either validates or fails.

## Fork policy

`fork_turns` continues to accept `none`, `all`, or a positive integer string. Omission continues to mean `all`.

| Fork selection | Profile override |
|---|---|
| `all` or omitted | Rejected when either override field is present. |
| `none` | Allowed. |
| Positive bounded count | Allowed. |

A full-history child without an override continues to inherit the parent run profile under ADR-0108.

## Persistence and lifecycle

Add `spawn_override` to `InferenceProfileSource` and its PostgreSQL enum.

No new `SessionAgent` or `AgentSession` model-profile columns are required. Existing `AgentRun` inference fields and `AgentSession.last_model_target_label` / `last_reasoning_effort` remain the storage contract.

The spawn path should execute in this order:

1. Parse and validate `fork_turns`.
2. Validate the current participant and concrete parent run.
3. Reject a full-history/profile-override combination.
4. Resolve the target and validate or normalize effort.
5. Compute the effective context window and compaction threshold for a changed target.
6. Create the child participant and hidden session.
7. Precreate the resolved first child run with `parent_agent_run_id`.
8. Initialize the child session's last-used requested profile.
9. Append selected forked context and the delegated task message.
10. Commit the transaction.
11. Publish child-tree activity and the payload-free broker wake-up.

Steps 2 through 9 must fail atomically. A provider invocation failure after wake-up remains an ordinary child run failure; static request validation must not leave an orphan child.

## Later child runs

The spawn-selected requested target label and effort become the child session's last-used profile. A later `followup_task` carries only delegated input. The normal worker precedence therefore selects:

1. an explicit pending input profile, if a future input type supplies one;
2. the child session's last-used requested profile;
3. the Agent default only if the child session has no last-used profile.

The first condition is not exposed by the current `followup_task` schema. The child is not permanently pinned to the first run's resolved snapshot; later runs resolve the stored label through the current Agent snapshot like other sessions.

## Errors

The tool should return a model-visible validation error and create no child for:

- unknown `model_target_label`;
- unsupported explicit reasoning effort;
- an override combined with a full-history fork;
- missing or incomplete parent run inference provenance;
- invalid `fork_turns`;
- existing child name or other current spawn limit failures.

Existing typed run failures remain available for failures that can occur only after child activation, such as integration availability or provider invocation failure.

## Security and permissions

- Resolve labels only inside the owning Agent and Workspace boundary.
- Do not accept or project integration ids, credentials, raw provider errors, or full catalog metadata in the tool schema or result.
- Existing subagent depth, concurrency, session tree, toolkit execution mode, and human-write boundaries remain unchanged.
- Model selection does not expand the child tool or filesystem permission boundary.

## Migration and rollout

- Add the nullable tool fields without a legacy alias.
- Add `spawn_override` through a generated Alembic revision and update the schema revision pointer.
- Regenerate the public API client only if a public schema includes the expanded inference source enum. The collaboration tool schema itself is runtime-generated.
- Existing calls that omit the fields retain exact parent-run inheritance.
- No data backfill is required.

## Test Strategy

### E2E primary matrix

Use an Agent with at least two deterministic selectable model targets whose effort capabilities differ.

Verify:

- omitted override inherits the concrete parent run model and effort rather than Agent defaults;
- model-only override preserves, lowers, or raises effort according to the canonical transition rule;
- explicit supported effort is applied;
- explicit unsupported effort fails without a child appearing in the Subagent Tree;
- unknown label fails without child/session/run residue;
- `fork_turns = all` rejects overrides;
- `fork_turns = none` and a bounded count allow overrides;
- a later `followup_task` reuses the child session's last-used requested profile.

The evidence should include parent and child run summaries, Subagent Tree state, and persisted run provenance. Deterministic fixture catalog entries are required so capability and resolved-model assertions do not depend on live provider metadata. Live provider tests are optional and must skip only when credentials or provider availability are absent.

### Backend coverage

Add focused tests for:

- the four input combinations in the profile derivation matrix;
- null and every relative effort-normalization branch;
- full-history rejection before repository mutation;
- transaction rollback on target or effort validation failure;
- `parent_run` versus `spawn_override` provenance;
- changed-target effective context and compaction limits;
- child last-used profile and follow-up resolution.

### Prompt and schema coverage

Assert that the generated `spawn_agent` description:

- uses the Codex V2-aligned preferred-inheritance wording;
- lists all Agent-owned labels and supported effort values;
- contains no provider name, physical model identifier, model display name, integration id, or snapshot metadata;
- does not add generic small/cheap/fast target-routing guidance;
- explains that full-history forks inherit the parent Run profile.

### Frontend and fixture impact

No new product UI is required. Update tool-schema snapshots and any deterministic subagent fixtures that assert the exact `spawn_agent` schema. Add Subagent Tree assertions only for the no-orphan failure boundary and resulting run metadata.

## Open questions

None for the current default-subagent scope. Predefined profiles require a separate feature design after this capability exists.

## Alternatives considered

The rejected alternatives and long-term consequences are recorded in ADR-0124.
