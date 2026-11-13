---
title: "Context compaction"
created: 2026-05-10
tags: [backend, engine]
---

# Context compaction

Bounded model context, durable summaries, memory boundaries and preserved pending work.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Memory](../domain/memory.md)
- [Conversations and events](../domain/conversation.md)
- [Agent execution](agent-execution-loop.md)
- [Run recovery](run-resume.md)
- [Agent](../domain/agent.md)

Planning, owner fencing and model-input-head mutation use the common execution
record. They require neither a public Conversation profile nor a participant
tree, and never manufacture public fields for an internal Session. The existing
Event/Run identities and adjacent append/head commit boundaries remain unchanged.

Context compaction keeps long session history within model input limits without
synchronously deleting audit/UI history. The event runtime uses append-only
compaction. A separate administrator-configured retention policy may later
permanently delete expired pre-head history; its default is Unlimited.

Automatic compaction effective context window is computed by
`engine/context/window.py`. Each option first resolves a default input window and
maximum input window from its normalized capability, using the maximum as the
default when the distinct default is absent. Only missing saved maxima request indexed exact
current source-model reads; paired foreground/lightweight calculations share one coherent
exact-key view without restoring the full source. Saved maxima take precedence, known defaults
remain a floor, and the 128,000-token fallback applies only when all limits are absent.
An unset option cap uses that resolved default; an
explicit option cap is clamped to the resolved maximum.

Each physical compaction candidate carries its saved normalized pricing definition.
Call-local capture adds aware dispatch time without price DB/source lookup and keeps
candidate-specific estimates stable across catalog refresh. Historical missing prices
remain unavailable, with no per-read enrichment or change to text-only title behavior.

For each prepared inference-bearing input, runtime then takes the prompt-selected
foreground candidate's resolved effective window and the Agent lightweight Primary's
resolved effective window and uses the smaller value as
`effective_max_input_tokens`. An option context cap is stored as intent and may be
larger than its current model maximum; the maximum still wins. Effective lightweight resolution
starts from the Agent's stored lightweight label Primary candidate and settings. A required
compaction operation freezes the label's ordered candidate chain separately from foreground
sampling. Workspace defaults are copied into the Agent only at create time and are not read by
runtime compaction. Automatic compaction threshold is then computed by
`compute_auto_compaction_threshold_tokens()` as `int(effective_max_input_tokens * 0.9)`. Both values are stored in the current `AgentSession` inference snapshot and remain fixed for one model-call attempt. After an automatic retry backoff, the next model attempt freshly resolves the current Session-applied profile and may replace both values before execution; recovered retry state follows the same boundary. A later prepared profile may also replace them at the next ordinary turn boundary, including within the same active run. The event runtime uses this Session-owned calculation as the compaction trigger source of truth and compares the threshold against the latest turn marker `usage.prompt_tokens` plus the
model-visible token estimate for events appended after that marker. If no turn marker exists, it falls
back to estimating the full selected transcript.

## Input Limit Recovery

Foreground execution also forces ordinary append-only compaction when the
complete lowered request exceeds the local 16,000,000-character guard or the
sampling provider reports a classified `context_limit`. This recovery bypasses
the automatic token threshold, with reasons `native_request_size_exceeded` and
`provider_context_limit`. Request-size inspection includes materialized image
data, tool definitions and model options; it is distinct from token estimation.
Both OpenAI Responses and Pydantic AI lowerers use the same foreground recovery.

One model turn may recover once: end the failed preparation's turn hook, honor
stop/mailbox and ownership boundaries, compact the current durable transcript,
then rebuild the native request and request-local dependencies from the summary.
The retry stays in the same Run and does not rerun completed client tools.
Before compaction, the Engine queues an internal `RunModelAttemptDiscarded`
instruction after any failed stream deltas and before recovery phase/output
events. Worker consumption validates the Run identity and invokes its existing
owner-fenced failed-attempt partial removal. The instruction is not published
to participants; old text/reasoning/tool partials cannot concatenate into the
replacement stream.
Ordinary compaction may remove image pixels; the Agent may read their source
files again in subsequent turns. No pending-image retention or automatic reread
is performed, and the original events/files are not deleted by compaction.

If compaction cannot produce a summary, is unavailable, or the rebuilt request
still exceeds either input limit, execution raises a user-visible
`model_input_too_large` non-provider failure. Worker finalization does not back
off or repeatedly send the same oversized input. Compaction provider failures,
stale plans, ownership loss and cancellation retain their existing handling.
Other sampling provider failures do not trigger this recovery.

## Behavior

When compaction is required:

1. Select the full ID-ordered model-input transcript and capture its current
   head and tail event IDs through a completed repository-owned planning
   operation.
2. Publish the Run-scoped live operation `preparing_context` and dispatch the compaction-start lifecycle hook. The external model and hook calls run outside compactor-owned database sessions and hold no active transaction or session-row lock used for event ordering.
3. Generate the summary through the provider-specific adapter. Provider failures propagate through the common bounded `ModelProviderFailure` contract to the owning Run controller.
4. Render bounded continuity history from the selected transcript, but keep it separate from the generated summary.
5. Dispatch the compaction summary enrichment hook pipeline with the generated summary and rendered continuity history.
6. Append the continuity history after the enriched summary.
7. A completed repository-owned finalization operation opens one short database
   transaction, fences the exact captured execution-owner generation when
   execution-bound, locks the Session, and revalidates both captured boundaries. A
   changed head or latest non-reverted event ID makes the plan stale and writes
   no compaction event.
8. For a current plan, append adjacent `compaction_marker(status=started)` and `compaction_summary` events with the same `compaction_id` and reason at the physical transcript tail. The summary payload contains the enriched checkpoint followed by bounded `Recent User Messages` and `Recent Transcript` sections.
9. Record the summary creation timestamp as `events.compacted_at` on newly displaced events, preserving earlier timestamps. Move `agent_sessions.model_input_head_event_id` to the summary event, replace the Session's `tool_search/working_set.tool_names` with an empty list, and commit the same transaction. The Tool Search reset applies even when the Agent currently has Tool Search disabled; other Toolkit State identities are unchanged.
10. Remove the live operation after success, Stop, cancellation, or terminal failure. A skipped, failed, cancelled, or stale attempt appends no compaction marker or summary, does not move the model-input head, and does not reset the Tool Search working set.

Run-owned compaction settlement is enabled by typed model-operation completion
authority on the execution context, not a live-session Worker callback. The
existing compaction repository directly composes the COMPACTION success mutation
with summary/head and Tool Search writes; foreground terminal settlement remains
in its separate output-completion operation.

Old events remain queryable. The head pointer changes which ascending event-ID range is used for
future model input. Input appended while summary generation is running invalidates the fixed plan;
the completed summary is discarded without a marker or head change, and a later attempt rebuilds
from current durable history.

## Memory Context Boundary

Conversation Memory selection is independent of transcript summary generation.
Root Run-start preparation selects a Saved index and whole current Team/personal
scope results. `on_session_compact` marks pending refresh, and reconstruction
refreshes only after a committed summary head; failed/stale compaction admits no
new selection. The compaction transaction does not write the Memory snapshot.
Unchanged content reuses its text and creation time. Child executions inherit
the root selection rather than independently selecting new results.

Each integrated result is a whole independently framed 10,000-byte document.
User context may compose Team and personal documents for up to 20,000 bytes;
there is no ranking, packing or source-summary fallback. Other turns reauthorize
current scope permission while preserving frozen selected bytes. Original source
versions, archive state and full manifests are not aggregate-access authority.
An independently permitted peer remains available when one scope is denied.

Prompt filtering uses read-only common root/Agent/Workspace/User scope authority.
Snapshot mutation retains owner-generation/head/CAS fences. Native opaque replay
compatibility follows the actual permitted semantic prefix; it has no aggregate
revision or inherited source-dependency identity. Explicit Memory VFS reads can
observe a newer current result without changing frozen context. A failed
compaction cannot create a new selection boundary because the head is unchanged.

### Internal Memory execution compaction

The summary-only Memory purpose host reconstructs dialogue and tool results from
its common Session Event transcript and committed model-input head. It measures
the actual lowered model/tool request against the selected resolved input window
and uses the common EventCompactor when the normal context threshold is exceeded.
The shared checkpoint task receives the current canonical transcript projection;
marker/summary/head writes are fenced by the same Session owner and Run commit
identity as conversation execution.

Compaction preserves the current execution files, pending correction, provided
summaries and useful checkpoint state in the same Session/Run. It does not
republish an aggregate, create a fresh Memory execution or reset its deadline or
consumed turn count. An oversized post-compaction request remains a compaction
failure rather than receiving an invented input/output budget. Common
physical-send admission rejects lost owner or cancellation before each SDK wire
request and does not map admission denial into provider quota failure.
See [`memory.md`](../domain/memory.md) for explicit submission and scope access.

## Summary Model

Summary generation uses the shared provider operation from
`engine/provider_model_operation.py`. OpenAI API-key and ChatGPT OAuth use the
foreground Responses lowerer, adapter and normalizer; other provider identities
use the foreground Pydantic AI lowerer, adapter and official SDK boundary.
For Conversation execution, a new compaction operation compiles exact authorized LOCAL metadata for the
configured Lightweight chain before normalizing controls and freezing candidates.
An existing compaction operation resolves its current captured candidate without
mutable metadata lookup; retries and quota progression retain that capture.
The Run request carries a deep copy of the complete selected candidate and its
model settings through fresh resolution, recovery and quota handoff. Its context
cap participates in the effective input window. Its explicit output setting
receives the same saved-model maximum clamp as foreground, while an unspecified
output cap stays unspecified. Internal Memory compaction instead uses the exact
already captured current Lightweight host candidate, credentials and resolved
window. Its physical compaction usage joins the common Run observations.
Summary calls declare no client or hosted tools.

Compaction summary generation is not user-facing streaming output, although the transport uses a
stream so the common watchdog can enforce parsed-event idle and absolute attempt deadlines. The
shared effective-request normalizer validates final feature membership and
conditions after provider-specific encoding. Genuine effort omission can use a
known captured default for condition evaluation; cleared, budget-only, disabled
and adaptive thinking keep their encoded kinds. Native structured output and
synthetic function output are admitted independently. The standard
provider operation sends ordinary user input plus top-level instructions through
the foreground request contracts. Compaction shares the enclosing Run's keyed
transport policy and HTTP-only fallback state; the operation-scoped SDK closes
on every exit. ChatGPT OAuth uses complete input, `store=false`, encrypted
reasoning inclusion, and no `previous_response_id`. Both provider families
use the selected output setting and validate protocol-native completion before
admitting a summary. Both adapter families
preserve only a bounded redacted provider message and typed safe
diagnostics for classified provider failures. A normalized compaction `quota_or_billing` failure
records the candidate outcome, shares its Workspace cooldown, and advances immediately to the next
compatible frozen lightweight candidate without consuming same-candidate retry. Other classified
compaction provider failures consume the active model turn's standard full retry budget; the next
attempt rebuilds from current durable history while preserving the compaction operation slot. An
unclassified provider outcome bypasses compaction provider retry state and follows the ordinary
internal-error path. Manual compaction uses its command Run's same failed-run controller and fresh
operation chain. Provider retry hints are diagnostic and do not replace the standard backoff schedule.

The stored checkpoint representation budget is based on the model context window:

- target summary chars: 3% of context window tokens, converted with 1 token ≈ 4 chars;
- limit summary chars: 8% of context window tokens, converted with 1 token ≈ 4 chars;
- target chars are nearest-rounded to 1000 chars and clamped to 12k–24k chars;
- limit chars are nearest-rounded to 1000 chars and clamped to 16k–50k chars;
- unknown context windows use a 128k token fallback.

This character budget controls the retained checkpoint representation, not
provider output generation. Input fitting reserves an explicit selected output
cap when present, plus the existing prompt overhead, within the resolved
effective window.

The runtime char guard allows a 10% tolerance over `limit_chars`. It computes
`truncate_chars = ceil_to_1000(limit_chars * 1.1)`. If a model returns more than `truncate_chars`, the
runtime performs a simple deterministic truncate and appends `[Truncated by Azents compaction guard.]`.
The runtime does not perform section-aware truncation or retry-based re-summarization.

The summary prompt asks for an execution-ready handoff checkpoint. It applies the transcript
chronologically as task-state transitions, identifies the active objective and current execution
state, preserves the furthest verified progress, and produces ordered next actions. Its structured
sections cover the active objective, current execution state, completed work, next actions, active
constraints and decisions, relevant files and identifiers, verification, and references. It uses
`Needs verification` only for uncertainty that materially affects a next action.

Checkpoint detail scales with task complexity rather than a fixed target length. Concise structure
removes repetition and conversational narration while retaining continuation-relevant state and
evidence. Complex or multi-stage work preserves the details needed to continue directly from the
checkpoint, including evidence of completed work and conclusions from resolved questions. Simple
work remains brief, and task complexity determines checkpoint length.

Auto and manual compaction include the full supported summary projection of the
selected transcript in the summary request. External Channel projection includes
only invocation-role messages; context-role messages remain available only through
bounded Recent Transcript continuity. The summary prompt asks for durable state from
the projected compacted transcript and warns that no raw event should be assumed to
remain available outside the checkpoint. After the model returns the checkpoint,
the runtime renders bounded continuity history separately, dispatches compaction
summary enrichment hooks, and then appends the continuity history to the stored
summary content.

Previous compaction summaries are rendered as existing checkpoints and treated as the previous state
to update. Later user direction updates the active objective, completed actions update the execution
state, and later tool or repository observations update earlier assumptions. Replaced approaches
remain only when they explain an active constraint or prevent duplicated investigation.

Manual compaction uses the same prompt, budget policy, continuity event policy, and summary
enrichment pipeline as automatic compaction. Manual compaction runs inside a `RunContext`, dispatches
`on_session_compact` with that run id, and passes the same run id to `on_compaction_summary`. It
publishes the same `preparing_context` live operation. A failed attempt leaves prior events and the
model-input head unchanged, then flows through the command Run's retry/finalization boundary without
writing a per-attempt compaction marker.

## Token Estimation and Filters

Automatic compaction does not re-estimate the full event transcript when provider usage is
available. It uses the latest turn marker usage as the accounted prefix and estimates only the event
delta after that marker. The estimator computes model-visible byte cost first and converts it with
`ceil(bytes / 4)`. It excludes storage metadata, native artifacts, event IDs, timestamps, and schema
fields, and counts only user/assistant text, client tool call name plus its model-visible argument
projection, client tool result text, provider-tool semantic transcripts, compaction summary text, and
bounded file/attachment/artifact metadata that can reach model input. JSON-function calls contribute
their arguments. Plaintext-custom calls contribute a fixed omission marker instead of their custom
input, so that input neither affects automatic-compaction accounting nor enters the summary-model input,
generated checkpoint, or continuity projection. Provider call events use the same deterministic semantic renderer
as model lowering, including input, textual output, typed references, optional excerpts, canonical
file/attachment metadata, and stable sorted metadata; native artifact JSON is never counted.

Before lowering model input, event pre-lower filters may update attachment/file availability projections and
run automatic compaction. They do not run Artifact, ExchangeFile, or ModelFile cleanup; file cleanup is
scheduler-owned. They do not omit old tool outputs for context pressure. Adapter-native request guards
run after lowering and do not mutate DB state.

## Summary Enrichment Hooks

After summary generation succeeds, the runtime dispatches the `on_compaction_summary` hook pipeline
to active toolkit providers. The hook context receives the current summary and the rendered continuity
history as separate strings, plus compaction/session/run metadata. Hook results may replace the current
summary. Providers that want additive behavior append to `context.summary` and return the full
replacement summary. Hook exceptions fail open: the runtime records hook failure telemetry and keeps
the current summary so compaction can continue. Toolkit implementations are not required to register
this hook.

The hook pipeline may only replace the summary portion. The runtime always appends continuity history
after the pipeline completes, so toolkit enrichment can be inserted between the model-generated
checkpoint and continuity, while continuity remains last in the stored `compaction_summary` content.
Todo Toolkit uses this hook to append a readable `Todo Snapshot` section when the session Todo list is
non-empty; it does not render a Todo section for empty state. Goal Toolkit uses the same hook to
append a readable `Goal Snapshot` section when the session Goal is unfinished and non-empty; it does
not render a Goal section for empty or completed state.

When the completed summary is lowered for the next model turn, its compaction reminder directs the
agent to combine the latest user messages and Goal Snapshot into the current objective, and current
repository/tool observations, recent tool results, and Todo Snapshot into the execution stage. The
agent starts from the furthest completed and verified progress and continues with the next unfinished
action.

## Continuity Events

After summary enrichment completes, the event compactor appends bounded continuity excerpts to the
summary payload content. This is not a separate raw tail in the event transcript. Future model input
starts at the summary event, and the continuity excerpts are part of that summary event's
model-visible text.

The `Recent User Messages` section contains the last five direct user-input events
from the selected transcript: ordinary `user_message` events and External Channel
messages whose `prompt_role` is `invocation`. External Channel context messages do
not enter this section. Selection is independent from recent model-turn boundaries
so a long tool-heavy request can still surface the user's latest requests even when
the recent transcript window contains no user messages. Items are numbered without
repeating a per-item user-message label.

The `Recent Transcript` section uses `turn_marker` events as completed model-turn
boundaries. It includes events after the marker preceding the last five completed turns. If five or
fewer completed turns exist, or if no turn marker exists, it falls back to all selected events. Each
excerpt is rendered as concise, readable model-visible transcript text rather than event storage JSON.
Transcript labels stay short (`User`, `Assistant`, `Tool call`, `Tool result`), and client tool
results render only their model-visible output rather than wrapper fields such as
`function_call_output`, `call_id`, or `output`. Provider-tool calls render their canonical semantic input, output, and typed references through the
shared deterministic renderer; output parts contribute bounded file/attachment/artifact metadata
through that rendering. The projection family matches token
estimation: user/assistant text, client tool call name/arguments, client tool result text,
provider-tool semantic transcripts, compaction summary reminders, system reminders, and bounded
file/attachment/artifact metadata. Event IDs, timestamps, native artifacts, event kind, and
storage-only metadata are not included.

For plaintext-custom client calls, the continuity call-argument slot is the same fixed omission marker
used by token estimation. The corresponding result remains ordinary bounded model-visible result text.
Compaction does not rewrite durable call events, select a different dialect, or make a custom call
executable on a later incompatible route.

Each user-message or transcript excerpt is truncated independently to 2,000 estimated tokens.
Truncation is marked inline with `[Event truncated by Azents continuity guard.]`. This prevents a
single large tool output from surviving compaction as an unbounded raw event while still preserving
the immediate shape of the recent interaction.

## Invariants

- Compaction is append-only: success atomically appends one adjacent marker/summary pair; failure or cancellation appends no compaction lifecycle event.
- Successful compaction resets only the Session's `tool_search/working_set` in the marker/summary/head transaction. A skipped or unsuccessful attempt preserves that working set, and all other Toolkit State remains unchanged.
- External summary generation and enrichment run before the successful commit transaction opens and do not hold a Session row lock.
- Planning is an ordinary read, independent of execution-tree locks. The final
  marker/summary/head/Tool Search reset group retains exact owner exclusion
  through commit, including execution-bound finalization without a model-operation
  commit context. Unowned dependency factories pass that absence explicitly.
- Events appended during external summary work make the plan stale; the attempt writes no marker or summary and leaves the model-input head unchanged.
- Summary failure or cancellation leaves the model-input head unchanged.
- Successful compaction writes the trigger reason to both `compaction_marker.payload.reason` and `compaction_summary.payload.reason` so context/debug views can explain why the checkpoint was created.
- `model_input_head_event_id` points at the summary event after successful compaction.
- Future model input is selected and sorted by event ID.
- Auto and manual compaction present future model input as one `compaction_summary` head event.
- The summary model receives the full supported summary projection of the selected
  transcript, without a protected tail; External Channel projection includes only
  invocation-role messages.
- Compaction summary hooks may replace only the summary portion; continuity history is appended after
  hook dispatch completes.
- Todo summary enrichment appends a `Todo Snapshot` section only when Todo state is non-empty.
- Goal summary enrichment appends a `Goal Snapshot` section only for unfinished non-empty Goal state.
- Scheduled summary enrichment replaces one bounded Scheduled Task section with
  sanitized current started-cycle snapshots in deterministic order. It omits
  admitted and terminalized cycles and does not mutate Toolkit State.
- The stored summary content includes a bounded `Recent User Messages` section from
  the last five ordinary user messages or External Channel invocations and a bounded
  `Recent Transcript` section from the last five completed model turns, using
  `turn_marker` boundaries.
- Continuity sections are always the last sections in the stored compaction summary content.
- Each continuity excerpt is rendered as readable model-visible transcript text, not event storage JSON.
- Provider-tool call continuity and token estimates use the same canonical semantic renderer and never parse native artifacts.
- Each continuity excerpt is independently truncated before it is embedded in the summary.
- Auto, manual, and fallback compaction share the same summary prompt and budget policy.
- Manual compaction uses the command run context when dispatching session compaction and summary enrichment hooks.
- Automatic and manual compaction expose one Run-scoped `preparing_context` live operation whose identity remains stable across retry and is removed at every terminal boundary.
- Every classified provider-attributed compaction failure uses the common bounded failure contract and the owning Run's full retry budget; unclassified provider outcomes are internal errors and do not enter provider retry state.
- Summary model calls use watched streaming transport without publishing user-facing deltas.
  All routes use the captured candidate settings and foreground output-cap clamp;
  checkpoint character retention does not create a provider output ceiling.
- Summary content is bounded by the runtime char guard after the model returns.
- UI/audit history includes retained pre-compaction events. ModelFile GC may
  delete unpinned ModelFile blobs behind the head; the separate
  `compacted_event_cleanup` task may then delete expired pre-head events according
  to first-displacement age and the current compacted-event retention policy.
  Cleanup preserves the current summary/head and later events, waits for the
  file-GC cursor and protects pending/running Run input references. Unlimited
  retention (the default) preserves original events indefinitely.
- Legacy SDK compaction packages are not part of production compaction.

## External Channel Continuity

All External Channel messages participate in model-visible token estimation and
bounded Recent Transcript continuity through their explicit source rendering.
Only messages whose `prompt_role` is `invocation` participate in summary-model
input and the bounded Recent User Messages section. Source rendering retains
provider, resource, sender, prompt role, and safe body instead of converting the
item to a direct Web-user message. Provider credentials, raw envelopes, and
arbitrary permalink Markdown are never included.

The immutable revision projected into a run remains the compaction input even
when provider-current state later changes. Corrections appear only when a later
authorized batch appends the corresponding revision event.

## Scheduled Task Continuity

Scheduled Toolkit enriches the generated summary before continuity history is
appended. It removes any stale Scheduled Task section and inserts current started
cycles ordered by their stable cycle state. Each entry retains the model-facing
cycle selector, title, objective, schedule, scheduled instant, progress title,
and ordered work items needed to continue autonomously. Internal Task, Run,
lease and provider-message identities remain omitted.

Goal and Channel Work snapshots likewise expose their exact logical selectors.
The summary is context, not authority: the Run's persisted work context and
canonical domain state survive independently of transcript retention. Scheduled
request preparation reconstructs applicable selectors from admitted references;
`get_goal` and scoped `get_channel_work` allow inspection when a summary enrichment
hook fails open. An unsuccessful or stale compaction creates no new work authority
or model-input boundary. Auto, manual and input-limit paths retain the same
enrichment-before-continuity ordering and atomic head settlement.

The enricher reads the current Session-scoped cycle Toolkit State and creates no
new durable authority. Task deletion, Session archive, or Binding disconnect does
not remove a preserved started cycle from the summary until that cycle
terminalizes.

## Routine Context Boundary

[Routine judgment](../domain/routine.md) reads canonical Session history but its
diagnostic observation is excluded from ordinary model input. Judgment-call usage
does not replace ordinary turn usage, latest normal system-prompt snapshot,
breakdown or compaction baseline. A no-action check therefore leaves ordinary
context and usage unchanged.

Admitted Routine trigger and continuation inputs are ordinary model inputs and
retain normal accounting. The Routine compaction hook adds every started,
unfinished occurrence in the exact Session, including earlier Run work. Each
occurrence retains its full immutable objective, source/prior context and identity
in deterministic order. It replaces its owned section, removes stale entries and
leaves other summary sections intact. Future registered definitions, unstarted
admissions and completed/cancelled work are excluded. Snapshot visibility does not
change execution ownership or permit completing another Run's occurrence.

Ordinary idle continuation remains separate: it selects the oldest eligible
incomplete occurrence, supplies one full context and references the remaining
identities. Neither path regenerates objectives from judgment.

## Model input limits and compaction budgeting

Each selectable model snapshot can carry a default input window and a maximum
input window. A missing default resolves to the maximum. For each option, an unset
`context_window_tokens` cap uses the resolved default; an explicit cap uses the
requested value up to the resolved maximum. Metadata from the local validated
current source-model exact-key read fills only a missing maximum; it cannot lower a
provider default. If maximum and source metadata are absent but a default exists,
that default supplies the maximum. The 128,000-token fallback applies only when
all three are absent. Library profiles and installed model maps are not fallback
authorities, and this resolution does not fetch remote source or model listings.

Main and lightweight calculations share one coherent capture of requested exact keys when
either saved maximum is missing. Known saved maxima require no source read for
context-limit computation. Agent list responses group only missing-maximum exact
keys across the entire list, without restoring a full source dataset.
Foreground resolution, compaction, subagent scheduling, worker calculations and
API displays use the same pure limit math and exact semantic model/source lookup.

Explicit selection copies the current catalog entry's normalized available or unavailable
pricing definition into every saved candidate. Primary, fallback, lightweight, compaction,
and subagent selection propagation preserves that definition without mutable price lookup.
Catalog refresh does not change saved prices. Historical selection JSON without pricing
decodes read-only as absent; actual dispatch leaves local estimation unavailable rather
than enriching or rewriting the selection.

`effective_context_window_tokens` in Agent response is calculated from the smaller
of the default main option's resolved effective input window and the default
lightweight option's resolved effective input window. A user cap may be larger than
the model maximum, in which case the maximum wins.
`effective_auto_compaction_threshold_tokens` is 90% of the effective context
window.

Prepared foreground turns use the prompt-selected option instead of the default main option for the foreground side of the same calculation. Automatic compaction runs with the lightweight model snapshot; the lightweight option context cap participates in input budgeting, but its `max_output_tokens` setting does not replace the compactor's dynamic summary output budget.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/engine/events`](../../../../python/apps/azents/src/azents/engine/events)
- [`python/apps/azents/src/azents/core/historical_memory_settings.py`](../../../../python/apps/azents/src/azents/core/historical_memory_settings.py)
