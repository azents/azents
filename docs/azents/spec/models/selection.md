---
title: "Model selection and operation snapshots"
created: 2026-11-04
tags: [wiki]
---

# Model selection and operation snapshots

Owns configured candidate chains, Workspace defaults, health and the exact inference profile frozen for an operation. Catalog discovery belongs to the model catalog; a saved choice and an active operation are different authorities.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Model catalog](../domain/model-catalog.md)
- [Agent](../domain/agent.md)
- [Subagent hierarchy and coordination](../execution/subagents.md)
- [Context compaction](../flow/context-compaction.md)

## Candidate chains and saved selections

`selectable_model_options` is a JSONB array rather than a separate table because option order is part of the fallback contract. The list invariants are:

- at least one option;
- at most 10 options;
- labels are trimmed, non-empty, case-sensitive, and unique within the list;
- labels are at most 80 characters;
- selected labels are normalized against the final list, and an absent selected label falls back to the first ordered option;
- every option stores one to five ordered candidates, where candidate 1 is Primary and later candidates are fallbacks;
- the same integration/model identity cannot appear twice inside one label, while separate labels may reuse it;
- every candidate stores `settings.context_window_tokens`, `settings.max_output_tokens`, and complete `settings.builtin_tools` name/config entries independently;
- replacing a candidate model in Agent settings retains compatible token caps and the enabled/disabled choice for every built-in tool supported by both models; newly supported tools start enabled, unsupported tools are omitted, and changing the provider integration clears provider-specific tool configs without resetting tool choices;
- nullable token caps mean no user cap, while an explicit empty built-in tool list disables all provider-hosted tools for that candidate;
- built-in configuration is scoped by semantic tool name. `image_generation` omits `config.model` for the maintained provider default and stores an exact provider identifier for an explicit pin; changing that field preserves unrelated configuration keys, while disabling the tool removes its complete entry;
- option-level `subagent_enabled` defaults to true and controls only whether the label is available as an explicit `spawn_agent` model target;
- option-level `subagent_guidance` is nullable parent-model routing guidance, is trimmed with blank input normalized to null, and is limited to 500 characters.

`model_selection` and `lightweight_model_selection` are `AgentModelSelection` JSONB snapshots and are not FK targets. They are effective runtime snapshots owned by Agent service consistency logic:

- `model_selection = selectable_model_options[main_model_label].candidates[0].model_selection`
- `lightweight_model_selection = selectable_model_options[lightweight_model_label].candidates[0].model_selection`

The denormalized snapshots are internal derived mirrors and are not public response fields. They
remain the Agent defaults and are fallback inputs only when a Session has no applied model profile;
an applied Session label takes precedence for future implicit turns.
When an Agent option update removes an applied label, the same transaction replaces that active
Session intent with the Agent's current main label and clears fallback-incompatible effort and
execution-option intent. Authorized active Session detail, list, and sidebar reads repeat the same
idempotent reconciliation for stale rows that predate the update transaction or were otherwise
left behind; this read repair changes only the applied next-turn intent. The current prepared turn
snapshot remains authoritative until its next model boundary. Normal human inputs may instead
request one label from the same Agent-owned option list for a single run. At fresh operation
preparation, the worker freezes that label's current ordered candidates without querying Workspace
defaults or model catalogs. A label accepted before an Agent option update that becomes stale before
preparation is normalized to the current Agent main label and persisted on the Session. Clients never
submit
provider, integration, model, capability, or token-limit snapshots as run intent.

Required snapshot fields:

- `llm_provider_integration_id`
- `provider`
- `model_identifier`
- `model_display_name`
- `model_developer`
- `model_family`
- `normalized_capabilities`
- `model_snapshot`
- `source_metadata`
- `last_refreshed_at`

Submitted exact integration/model IDs and ordered settings form user
configuration. `normalized_capabilities` has schema version `3`: final support is
represented by its boolean/list fields, with a separate `structured_response`
boolean and `request_constraints` for known defaults and feature conditions.
Source evidence and compiler diagnostics do not become another final support
state.

Agent detail/list responses and their chat model controls compile current
authorized LOCAL declarations for those same IDs and return detached metadata
copies. Lists batch exact choices by Workspace, including distinct existing
aliases. Missing required metadata retains the selected identity and reports a
diagnostic with empty support; it does not choose another candidate. Unrelated
PATCH and label saves persist user settings without copying response metadata
back into the Agent row.

NEW operations capture compiled metadata before profile preparation. Once
captured, retries, quota progression and historical execution use the operation's
candidate snapshots. Lowerers validate the actual encoded request against those
final fields and conditions without mutable catalog lookup.

Configuration controls use the complete final effort and built-in lists.
Conditional potential stays configurable until actual request admission evaluates
effective effort and function declarations. Existing effort ordering/adaptation
is retained for concrete model changes; valid values and explicit null are
preserved. The canonical domain is `none`, `minimal`, `low`, `medium`, `high`,
`xhigh`, and `max`; provider `ultra` remains raw declaration evidence only.

## WorkspaceModelSettings

`workspace_model_settings` stores default values for new Agent creation in Workspace.

| Field | Meaning |
|---|---|
| `workspace_id` | Workspace PK/FK |
| `default_selectable_model_options` | ordered default selectable model option list copied by new Agents. may be null before Workspace defaults are configured |
| `default_main_model_label` | selected default main model label. may be null before Workspace defaults are configured |
| `default_lightweight_model_label` | selected default lightweight model label. may be null before Workspace defaults are configured |
| `default_model_selection` | denormalized effective default main model snapshot. may be null initially |
| `default_lightweight_model_selection` | denormalized effective default lightweight snapshot. may be null initially |

`effective_default_lightweight_model_selection` is not stored column; it is computed as `default_lightweight_model_selection ?? default_model_selection` for consumers that need the fallback projection.

Rules:

- If Workspace default selectable model options are absent, creating Agent without explicit model options fails.
- Once Workspace defaults are configured, the default selectable model list cannot be cleared to empty.
- Workspace default selectable model lists retain Agent label, order and cap validation. Partial Workspace updates distinguish omission from explicit null.
- Omitted default main/lightweight labels retain their current values, including whole-option replacement if the selected label still exists. Removed labels fall back to the first ordered option; initial configuration with omitted labels also uses the first option.
- Explicit null requests a clear and is rejected with `DefaultModelCannotBeCleared`/HTTP 400 when defaults are configured or the request supplies a nonempty new option list. Rejection precedes candidate resolution and mutation; mixed requests are not partially stored.
- Empty unconfigured records retain their nullable representation and existing creation/rejection behavior. Empty/unknown string normalization remains separate from null. New Agents copy the selected Workspace labels; existing Agents are not changed by Workspace updates.
- Updating Workspace defaults recomputes the denormalized effective default snapshots from default labels.
- New Agents copy exact Workspace identities, order and complete model-scoped settings,
  including built-in configs, while capturing current compiled capabilities for those
  choices. Existing Agents retain their user configuration when Workspace defaults change.
- Public Workspace mutation accepts only the nested default candidate-chain contract. The
  denormalized default snapshots remain internal derived mirrors.

## Workspace candidate health and Session Primary reservation

`model_candidate_health` is the PostgreSQL authority for short-lived availability of one physical
candidate identity inside a Workspace. Identity is the Workspace, provider integration, and provider
model identifier. A normalized quota or billing failure advances its health generation, starts a
five-minute cooldown, and revokes any older foreground probe or Session reservation authority.

After cooldown, one foreground operation may claim a generation-fenced half-open probe. Other
operations observe `probe_busy` and continue to later compatible candidates. Probe success clears
cooldown only when its claim generation is still current; quota failure starts a new cooldown at a
new generation. Lease expiry permits a later claimant, and stale completions cannot overwrite newer
health.

One root Session may store a bounded Primary-next reservation for its currently applied semantic
label and exact Primary identity. Reservation create, transfer to the next foreground operation,
cancel, success, and renewed quota are fenced by candidate health generation and reservation
generation. A stale identity or generation is not projected as `primary_next`. PostgreSQL remains
authoritative when Redis is unavailable or restored empty.

## Provider integration and model listing

`LLMProviderIntegration` is workspace-scoped credential/config. Its
`/catalog-entries` endpoint returns stored selectable model catalog entries.

The stable `xai` provider uses generic encrypted API-key secrets with no plaintext provider config. It remains a separate integration identity from experimental `xai_oauth`. Generic integration CRUD persists fake or real keys without calling xAI for validation, omits secrets from every public response, and preserves the encrypted key when an alias or enabled-state update omits `secrets`.

Agent/Workspace settings API resolves each client-sent `{ llm_provider_integration_id, model_identifier }` through the stored model catalog projection and normalizes it into an `AgentModelSelection` snapshot. This applies both to direct transition fields and to every selectable model option entry.

## Workspace model settings

```http
GET /workspace-model-settings/v1/workspaces/{handle}
PUT /workspace-model-settings/v1/workspaces/{handle}
```

PUT accepts Workspace default selectable model options and labels:

```json
{
  "default_selectable_model_options": [
    {
      "label": "default",
      "candidates": [
        {
          "model_selection": {
            "llm_provider_integration_id": "int_...",
            "model_identifier": "gpt-5"
          },
          "settings": {
            "context_window_tokens": null,
            "max_output_tokens": null,
            "builtin_tools": [
              {"name": "web_search"},
              {
                "name": "image_generation",
                "config": {"model": "gpt-image-2.5-flare"}
              }
            ]
          }
        }
      ],
      "subagent_enabled": true,
      "subagent_guidance": null
    }
  ],
  "default_main_model_label": "default",
  "default_lightweight_model_label": "default"
}
```

- `default_selectable_model_options` is whole-list replacement.
- Once configured, the Workspace default list cannot be cleared to empty.
- Labels, option count, model-scoped settings defaults, and per-option validation use the same invariants as Agent selectable model options.
- Default labels normalize to the first option when omitted, null, or absent from the final list.
- Response returns default selectable candidate chains and default labels. Denormalized effective
  default snapshots are internal derived mirrors; legacy direct model-selection mutation fields are
  not accepted.

## LLM provider integration models

```http
GET /llm-provider-integration/v1/workspaces/{handle}/llm-provider-integrations/{integration_id}/catalog-entries
```

The endpoint requires LLM integration read permission and resolves the integration
within the Workspace. It returns paginated stored selectable entries with optional
search and catalog status. The read does not call a provider; it can enqueue a
stale-catalog refresh. Agent/Workspace settings use this projection for pickers.

## Breaking-change upgrade guidance

The candidate-chain release is a coordinated clean-v1 cutover. Database migration converts every
existing label into one `candidates` entry while preserving its physical model, settings, selected
main/lightweight labels, and Workspace-to-new-Agent copy behavior. Deployments must stop old
readers/writers, apply the migration, and then start the complete new Server, Worker, Web, and
generated-client set.

Clients must replace singular option-level `model_selection` / `settings` with
`candidates[].model_selection` / `candidates[].settings`. Agent and Workspace public mutation no
longer accepts direct main/lightweight physical-selection fields, and public responses no longer
return denormalized effective-selection mirrors. Callers select main and lightweight behavior by
semantic label and treat the first candidate as Primary.

Before new-format writes, rollback requires the old application and database downgrade together.
After new-format writes, automatic downgrade is not a safe configuration collapse; restore by
roll-forward repair or an explicit operator-approved conversion that accepts candidate loss.

## Runtime Resolve

Every inference-bearing input has a requested inference profile: an Agent-owned `model_target_label`, nullable `reasoning_effort`, and an explicit `enabled_execution_options` list. Execution options are immediately switchable preferences, separate from static abilities and model-scoped built-in tool settings. Saved model selections advertise `supported_execution_options`; the public selectable-option response separately projects definition text, registry-owned exclusivity metadata, and provider-specific qualitative cost hints for the composer. Fast (`fast`) and Ultrafast (`ultrafast`) share the `processing_speed` group: support may include both, enabled intent includes at most one, and Normal is the empty selection. Saved support remains authoritative until the existing model refresh/reselection path updates it. Null effort means the selected model or provider default, not the Agent-level reasoning parameter. Normal user configuration and composer input always select a concrete effort when the selected model advertises explicit effort levels; `Default` is not a user-facing option. Agent settings place `Default reasoning effort` beside the default model control, and effort choices are rendered as raw lowercase enum values without localization. Models with an empty explicit effort list hide the control and use null. The request source is `explicit_input`, `session_last_used`, `agent_default`, `retry_original`, `parent_run`, or `spawn_override`.

Before an inference-bearing FIFO head is atomically prepared, runtime resolution:

1. Loads the Agent and rejects missing or disabled Agents.
2. Resolves the requested label against the Agent's current `selectable_model_options`; a label that was accepted earlier but is now absent falls back to the current Agent main option and replaces the active Session intent, while a label rejected at input admission still fails with `model_target_not_found`.
3. Validates every non-null requested effort against the selected snapshot's explicit normalized effort list; an empty list rejects every explicit effort, and unsupported effort fails with `reasoning_effort_unsupported` before provider invocation.
4. Loads and validates the selected main integration plus the Agent's lightweight integration, including provider token refresh where required.
5. Builds the foreground runtime model, output cap, and built-in tool list from the selected option while retaining the Agent's lightweight option for compaction.
6. Computes the prepared turn's effective context window from the selected foreground option's capped input limit and the lightweight option's capped input limit, then derives the automatic compaction threshold.
7. Validates remaining Agent model parameters, applies the requested effort, and materializes user attachments.

Preparation also validates enabled execution-option IDs against the implemented registry and selected saved model support. Unknown, duplicate, unsupported, or group-conflicting explicit selections fail before provider invocation rather than silently dropping the preference. Composer draft model switching may intersect choices with the new model's support without selecting another premium member; that client normalization does not replace server validation. Implicit inherited choices on an explicitly changed subagent target retain only supported options, while same-target and full-history inheritance preserve the prepared choice. Auxiliary title and compaction calls do not inherit premium sampling options.

Successful preparation atomically stores the full selected `AgentModelSelection`, selected `SelectableModelSettings`, enabled execution options, resolved effort, effective limits, and resolution timestamp on `AgentSession` with the canonical input effects and buffer deletion. The Session snapshot is immutable for the active model-call attempt. After an automatic model-call failure and retry backoff, the next attempt freshly resolves the current Session-applied profile against the current Agent option mapping and replaces that snapshot before provider invocation. Recovery performs the same refresh before resuming a persisted retry. A later prepared profile may also update the snapshot at an ordinary turn boundary within the same active `AgentRun`, forcing model/tool context to rebuild before the next model call. Resolution failures consume the failed FIFO head, preserve the previously committed Session snapshot, append a terminal typed user-safe error, and are never retried.

`spawn_agent` exposes only current Agent options whose `settings.subagent_enabled` is true. Each advertised entry contains the Agent-owned label, explicit effort levels, and optional bounded `subagent_guidance`, but not integration ids, providers, physical model identifiers, display names, families, catalog metadata, context limits, pricing, or resolved snapshots. Explicit target validation uses the same enabled-option set; missing and disabled labels fail with the same unavailable-override tool error before child creation. Omitted `model_target_label` preserves the exact concrete parent Session target even when that option is disabled, and an effort-only override retains that inherited target. If no option is enabled, inherited spawning remains available while no explicit target is advertised. An explicit target label or effort is allowed only with `fork_turns = none` or a positive bounded count; full-history forks reject overrides. A target-only override normalizes from the parent resolved effort using canonical effort order: preserve when supported, otherwise choose the greatest supported lower effort, otherwise the smallest supported effort, or null when no explicit levels exist. Explicit effort is validated exactly and never normalized. Static validation completes before child creation.

Runtime does not query Workspace defaults or model listing. Workspace defaults act only as copy sources at Agent create/update submit time, and model catalog changes do not mutate an already prepared Session snapshot.

## API route entrypoints

- `/chat/v1/agents/{agent_id}/sessions/{session_id}/model-reservation`
- `/chat/v1/agents/{agent_id}/sessions/{session_id}/model-reservation/cancel`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/core/active_model_capabilities.py`](../../../../python/apps/azents/src/azents/core/active_model_capabilities.py)
- [`python/apps/azents/src/azents/repos/engine_resolve.py`](../../../../python/apps/azents/src/azents/repos/engine_resolve.py)
- [`python/apps/azents/src/azents/services/llm_catalog`](../../../../python/apps/azents/src/azents/services/llm_catalog)
