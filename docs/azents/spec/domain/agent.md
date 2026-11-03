---
title: "Agent"
created: 2026-04-20
tags: [backend, engine]
---

# Agent

Persistent Agent configuration, management authority and create/update interfaces. Model selection, managed compute and cleanup are separate connected contracts.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Conversations and events](conversation.md)
- [Agent execution](../flow/agent-execution-loop.md)
- [Model catalog](model-catalog.md)
- [Agent deletion](agent-deletion.md)
- [Model selection and operation snapshots](../models/selection.md)
- [Runtime capability and profiles](../runtime/profiles.md)
- [Request capabilities and built-in tools](../models/request-capabilities.md)
- [Context compaction](../flow/context-compaction.md)
- [Projects, working folders and worktrees](../runtime/projects.md)
- [Memory](memory.md)
- [External Channels](external-channel.md)

Agent is central execution unit of azents. Within Workspace, it bundles an ordered selectable model option list, effective model selection snapshots, system prompt, model parameters, Toolkit access, and an optional managed Runtime capability; worker resolves these into `RunRequest` and passes them to `AgentEngine` execution loop. Session-scoped subagents do not create a separate persistent Agent role; they are represented by `SessionAgent` tree nodes linked to hidden child `AgentSession` rows under the same Agent.

The auto-bound Runtime Web Toolkit is available to root Agents and subagents only
while the Agent has managed Runtime capability. It requests or returns the one
Agent-and-port service in the Off state, lists the Agent's services, and turns an On
service Off. Agent execution cannot turn a service On, reset or extend exposure,
delete a service, or control the application process. Human management through any
Session or Agent settings operates on the same Agent-owned service.

## Core Model

### Agent

`agents` row has following core fields.

Agent profile settings include `routine_check_interval_minutes` (tick) and
`routine_min_action_delay_minutes`. Both are strict whole-minute integers with
`30 <= minimum action delay <= tick <= 1440`. New Agents default to tick 180
and minimum delay 30. Existing Agents transfer their old tick to minimum delay
with a 30-minute floor, then set tick to the greater of that delay and 180.
Both values use the existing authorized create/read/partial-update path.
Omitted fields are retained, except that supplying minimum delay automatically
raises tick to `max(supplied or stored tick, supplied delay)`. Lowering delay does
not lower tick. Tick-only updates below stored delay, invalid create pairs, null,
fractional and boolean values are rejected. Partial cadence updates serialize on
the current Agent mutation fence before normalization and merged-pair validation,
and a database CHECK enforces the same invariant. The form raises tick on valid
delay edits. See the [Routine spec](routine.md) for their separate references
and unchanged discovery, judgment and notification semantics.

| Field | Meaning |
|---|---|
| `workspace_id` | owning Workspace. restrictive parent FK prevents Workspace deletion from bypassing Agent lifecycle |
| `lifecycle_status` | `active` or `decommissioning`; decommissioning fences user-originated Agent-owned mutations and new work while preserving authorized inspection and native cleanup |
| `name`, `description` | display name and description |
| `selectable_model_options` | ordered JSONB array of selectable semantic labels. Each option has a unique label, label-scoped subagent policy, and one to five ordered physical candidates; each candidate owns a resolved `AgentModelSelection` snapshot and model-scoped runtime settings |
| `main_model_label` | selected label from `selectable_model_options` for normal model turns |
| `lightweight_model_label` | selected label from `selectable_model_options` for compaction/lightweight model turns |
| `model_selection` | denormalized effective main runtime model selection snapshot resolved from `main_model_label`. required for every Agent |
| `lightweight_model_selection` | denormalized effective compaction/lightweight model selection snapshot resolved from `lightweight_model_label`. required for every Agent |
| `model_parameters` | Agent-local advanced model parameters. Only this value is used without default/preset merge |
| `system_prompt` | Agent system prompt |
| `enabled` | when false, runtime resolve blocks run start with `AgentDisabled` |
| `type` | `public` or `private` |
| `runtime_capability` | `none`, `managed`, or `removing`. New Agents default to `none`; existing Agents were migrated to `managed` |
| `runtime_capability_version` | positive optimistic version for dedicated Runtime add/remove transitions and stale admission fencing |
| `runtime_profile_id` | nullable exact Workspace Runtime Profile selection for a managed Agent. Null does not imply Runtime-free state |
| `runtime_profile_selection_version` | positive optimistic version for replacing or clearing the Agent selection |
| `toolkit_management_available` | requester-relative true only for a Workspace Owner or explicit AgentAdmin of this active Agent; grants the enhanced saved-Agent Toolkit management flow but does not disclose any Toolkit state itself |
| `terminal_enabled` | Agent-owned default-true browser Terminal policy. It is independently editable from Runtime capability and never gates Worker Runtime Toolkit access |
| `browser_enabled` | Agent-owned opt-in Session Browser setting, default false for existing and new Agents. Runtime settings can enable tools and live-panel access independently of Terminal and other Runtime features. Disabling preserves native profile bytes. |
| `browser_implementation` | Agent-owned PostgreSQL enum: `patchright` by default, or experimental opt-in `camoufox`. Existing Agents migrate to Patchright without changing profile bytes or Runtime identity. |
| `browser_configuration_intent_id` | Opaque current replacement/CAS identity. ORM and database creation paths generate a fresh 32-character identity; replacement uses exact-current intent checks. |
| `browser_application_state` | PostgreSQL enum `applying`, `ready`, `failed`; the API derives `offline` from current Runtime/control evidence. |
| `browser_observed_runtime_id`, `browser_observed_runner_generation` | Nullable non-owning last application evidence, not foreign keys. Only the exact current Runtime/generation can admit browser work; replacement does not delete Agent settings. |
| `browser_application_claim_id`, `browser_application_lease_until`, `browser_application_next_at`, `browser_application_reason` | Bounded durable application claim, retry timing and failure evidence owned by Agent lifecycle. |

Browser configuration lives on the existing `agents` row keyed by Agent ID and
inherits its Workspace ownership and deletion ordering; no new owning relationship
or independent cleanup resource is introduced. Agent deletion removes these fields
with the row. Runtime removal/replacement retains requested engine intent and
invalidates stale application authority through current Runtime/generation checks.
The coordinator owns leased application and status reconciliation. Browser-only
switching does not alter Runtime infrastructure configuration, destroy profile
bytes or stop shells. Dedicated browser intent, claim and result writes preserve
the general Agent policy timestamp so they do not revoke unrelated live Terminal
authority; their own exact intent/current-Runner evidence fences browser access.
The [Session Browser flow](../flow/session-browser.md)
defines the dedicated settings API, authorization, source retirement and profile
separation.
| `memory_enabled` | gates Saved/Historical automatic context, preparation, mutation tools, and model-facing live Memory VFS access; retained human settings inspection remains available |
| `max_turns` | run turn limit. null means unlimited |
| `auto_archive_ttl_days` | positive whole-day inactivity TTL for automatic archive of this Agent's non-primary root Sessions. Defaults to `30` and applies dynamically to existing active Sessions |
| `external_channel_default_response_mode` | required `mention_only` or `all_messages` value copied into each newly selected provider-channel participation setting and into legacy isolated-thread Bindings that have no setup claim. Existing Agents default to `all_messages` |
| `subagent_settings` | JSON settings for session-scoped subagent execution limits. Default is `{ "max_subagents": 3, "max_depth": 1 }` |
| `avatar` | Agent avatar stored image metadata |

`subagent_settings.max_subagents` is the maximum active subagent count under one root session. It is equivalent to Codex `max_concurrent_threads_per_session - 1`; the root/current agent is not counted in the stored value. `subagent_settings.max_depth` is the maximum `SessionAgent` tree depth below `/root`, where `1` allows root-to-child spawning only. Both values are non-negative integers.

`auto_archive_ttl_days` is required and must be positive. Agent create and patch responses expose the configured value. Updating it changes eligibility for all existing active root Session trees at their next scheduler evaluation; it does not snapshot a TTL onto the Session.

`external_channel_default_response_mode` belongs to External Channel management rather
than the generic Agent create, response, or patch contract. Agent administrators read
and replace it through the Agent-scoped External Channel settings API. Provider-channel
location selection copies the current value into the new participation setting, and
later configured Bindings copy that setting. Legacy isolated-thread access replay
without a setup claim copies the Agent value directly. Later Agent default changes
never rewrite an active setting or existing Binding.

`terminal_enabled` controls only human interactive Terminal access. Agent create and
partial update expose the raw flag without requiring a currently managed Runtime. Agent
responses also expose infrastructure-Profile, Workspace-Profile, effective policy, and
the bounded denial scope. Effective access requires every policy level plus current
managed Runtime, ready Runner `terminal.v1` capability, Session access, and working-folder
authority. Runtime Toolkit projection instead depends only on managed Runtime capability
and its optimistic version; there is no Agent Shell setting or compatibility fallback.
The Agent form exposes the Terminal policy and its effective status only when create
currently selects a Runtime Profile or edit reports `runtime_capability=managed`.
Runtime-free create and edit forms keep the raw default or stored policy for submission
but do not expose Terminal controls or denial diagnostics.

## API Contract

Agent, Session and coordination descriptions do not acquire an Agent-wide,
root-tree or execution-owner row gate. Captured execution ownership can be
validated by a plain read; a description is not ownership handover or lifecycle
admission. Actual output and lifecycle mutations retain their existing exact
Session generation, resource, claim and status conditions through commit.

Subagent creation and follow-up capacity admission coordinate with the existing
root SessionAgent hierarchy row. Ordinary path/tree/status reads, message
inventory and single-target interruption do not inherit that root gate. Actual
collaboration mutations admit only their source/target Session rows in stable
order with ordinary waiting locks. A database-confirmed deadlock or serialization
abort releases the complete owning transaction before retry; recovery covers
either hierarchy mutation or terminal-delivery victim without replaying model,
tool or broker effects. Original source ownership and detached inputs are
retained and revalidated in a fresh scope. Source owner-generation validation is
fenced only after the required mutation rows have been admitted. Cancellation,
ownership loss and uncertain commit do not retry.

Stop, archive, restore, purge and decommission admit the existing root and its
current Session tree as a mutation boundary shared with child creation. A child
cannot escape an admitted transition through an enumeration race. Irreversible
purge cutoffs, exact attempts/leases, participant snapshots, tombstones and
already-started Scheduled results retain their existing semantics; policy and
lifecycle status descriptions do not claim destructive work.

### Agent create/update

Create/update requests accept selectable model options as the current model contract:

```json
{
  "selectable_model_options": [
    {
      "label": "default",
      "candidates": [
        {
          "model_selection": {
            "llm_provider_integration_id": "int_...",
            "model_identifier": "gpt-5"
          },
          "settings": {
            "context_window_tokens": 128000,
            "max_output_tokens": 8192,
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
      "subagent_enabled": false,
      "subagent_guidance": "Reserve for complex synthesis tasks."
    },
    {
      "label": "lightweight",
      "candidates": [
        {
          "model_selection": {
            "llm_provider_integration_id": "int_...",
            "model_identifier": "gpt-5.5-mini"
          },
          "settings": {
            "context_window_tokens": null,
            "max_output_tokens": 4096,
            "builtin_tools": []
          }
        }
      ],
      "subagent_enabled": true,
      "subagent_guidance": "Prefer for bounded investigation."
    }
  ],
  "main_model_label": "default",
  "lightweight_model_label": "lightweight",
  "model_parameters": {
    "temperature": 0.7,
    "reasoning_effort": "medium"
  },
  "subagent_settings": {
    "max_subagents": 3,
    "max_depth": 1
  }
}
```

- `selectable_model_options` omitted on create: copy Workspace default selectable model options into Agent.
- `selectable_model_options` supplied: whole-list replacement. Every candidate is resolved through stored catalog projection at submit time, and its settings are normalized against that candidate capability.
- Omitted candidate settings default to null token caps and every supported implemented built-in tool enabled. Option-level subagent targeting defaults to enabled with null guidance. Explicit null token caps preserve no user cap, and an explicit empty built-in tool list preserves all-off intent.
- Subagent guidance is trimmed and blank input becomes null. Guidance longer than 500 characters is rejected.
- Positive token caps are stored even when they exceed catalog capability limits; runtime clamps them against the resolved model snapshot. Duplicate or unsupported built-in tool names are rejected per candidate. Image-generation defaults and explicit pins are also validated against the selected candidate capability, enabled provider integration, reviewed registry, and current stored image catalog before save.
- Empty lists, more than 10 labels, labels with zero or more than five candidates, empty labels, duplicate labels, duplicate physical identities within a label, and unresolved model selections are rejected.
- `main_model_label` / `lightweight_model_label` omitted, null, or absent from the final list: fallback to the first ordered option label.
- Internal effective `model_selection` and `lightweight_model_selection` mirrors are recomputed from each final label's Primary candidate. Public requests and responses expose only the nested chains and selected labels.
- `model_parameters` is whole-object replace for the remaining Agent-global inference parameters such as temperature and default reasoning effort. Unknown keys are rejected; context, output, and built-in tool settings do not exist at Agent scope.
- Existing `top_k` is an Agent-local positive integer, not a per-prompt or preset
  override. Its exact nullable value is carried through Run resolution and model
  preparation. The installed Google, Anthropic and applicable Bedrock codecs
  transmit it; a codec without an adopted mapping fails before provider dispatch.
  Saved support predicates and denials remain authoritative, and saved selections
  are not rewritten to make the parameter available.
- `subagent_settings` is a whole-object replace when supplied. Omitted create requests use the default `{ "max_subagents": 3, "max_depth": 1 }`; omitted update requests leave the stored settings unchanged.
- `runtime_profile_id` omitted or null on create produces a Runtime-free Agent and does not copy the
  Workspace default. An explicit available Profile produces a managed Agent.
- `runtime_profile_id` on generic update is managed-only and remains a partial-update field:
  omission leaves the selection unchanged, explicit null clears it, and a non-null value replaces
  it. The request must include `expected_runtime_profile_selection_version`.
- Runtime Profile selection changes do not directly issue a lifecycle command or recreate physical
  compute. The exact selection-version-fenced mutation atomically overwrites the authoritative
  desired current configuration state at a higher Runtime configuration sequence; an explicit
  clear writes `unconfigured/runtime_profile_required`, clears desired Provider/Runner
  acknowledgement evidence, and preserves any applied incarnation. Current lifecycle guards decide
  whether explicit recreation is required.
- Response returns stored `selectable_model_options`, `main_model_label`, `lightweight_model_label`, `model_parameters`, `subagent_settings`, and effective context window value.

## Memory / toolkit / avatar

- Agent with `memory_enabled=false` suppresses automatic Memory context,
  Historical discovery/preparation, Saved mutation tools, and model-facing
  Memory VFS access; retained human settings inspection remains available.
- Toolkit CRUD, ownership, OAuth, and runtime state follow [`toolkit.md`](toolkit.md). A saved Agent response includes requester-relative `toolkit_management_available`; it is derived from Workspace Owner or explicit AgentAdmin authority for that exact active Agent. When false, saved-Agent settings retain the legacy shared attach/detach section and disclose no Agent-only Toolkit state. When true, `Add Toolkit` opens a two-tab tile catalog with new Agent-only Provider selection as default and a separate existing Workspace Toolkit tab. Additions persist through their own operations without submitting the Agent form; compact connected cards open allowlisted details and existing ownership-correct actions. Agent creation and Chat remain unchanged.
- Avatar is stored as stored image metadata through upload service image handler and resolved to public URL in Agent response.
- Main Web provides available avatar variants as responsive width candidates and
  declares the rendered CSS width, allowing the browser to select a thumbnail that
  covers the current display pixel density without always downloading the largest tier.
- Avatar replacement and removal lock the Agent row, update the current avatar,
  and atomically enqueue an immutable cleanup snapshot for the previous avatar.
  The public API result does not wait for old-blob deletion.
- Superseded-avatar cleanup jobs keep an optional diagnostic Agent reference with
  `ON DELETE SET NULL`, so Agent deletion cannot erase deletion responsibility.
  Each scheduler cleanup pass uses a unique opaque claim token to lease bounded
  due jobs, deletes the deduplicated avatar files, retries failures with bounded
  backoff and stack-trace logging, and deletes the cleanup row only when the
  exact claim token still owns it.
- Publication failures before a newly processed avatar is adopted by the Agent
  row are not recovered by the superseded-avatar cleanup lifecycle.

## Removed Legacy

Following contracts do not exist in current system.

- `ModelConfig` table/service/repository/API
- `/model-config/v1/**`
- `agents.model_config_id`
- `agents.lightweight_model_config_id`
- `agents.model_config_inherit_mode`
- `agents.model_parameter_overrides`
- runtime `ModelConfig` lookup / default parameter merge
- legacy subagent role, junction, API, and blocking runtime delegation tool
- legacy persistent subagent-Agent model inheritance

## API route entrypoints

- `/agent/v1/workspaces/{handle}/agents/{agent_id}/admins`
- `/agent/v1/workspaces/{handle}/agents/{agent_id}/avatar`

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/agent`](../../../../python/apps/azents/src/azents/services/agent)
- [`python/apps/azents/src/azents/repos/agent`](../../../../python/apps/azents/src/azents/repos/agent)
- [`python/apps/azents/src/azents/rdb/models/agent.py`](../../../../python/apps/azents/src/azents/rdb/models/agent.py)
