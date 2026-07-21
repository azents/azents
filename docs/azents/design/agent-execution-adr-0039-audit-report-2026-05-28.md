---
title: "[execution-260527/ADR](../adr/execution-260527-execution-transcript-normalization.md) Application Audit Report"
created: 2026-05-28
updated: 2026-05-28
tags: [architecture, backend, engine, audit]
document_role: supporting
document_type: supporting-audit
migration_source: "docs/azents/design/agent-execution-adr-0039-audit-report-2026-05-28.md"
---

# [execution-260527/ADR](../adr/execution-260527-execution-transcript-normalization.md) Application Audit Report

## Audit Scope

Audit criteria are the 26 items under `## Decisions` in [`execution-260527/ADR: Agent Execution Transcript Normalization`](../adr/execution-260527-execution-transcript-normalization.md).

This audit re-evaluated based on implementation state. Follow-up changes from PR #4132 are reflected up to shadow table cutover, canonical REST history projection, input buffer canonical persistence, and SDK RunState column removal.

Main code paths checked:

- `python/apps/azents/src/azents/runtime/canonical/`
- `python/apps/azents/src/azents/repos/agent_execution/`
- `python/apps/azents/src/azents/repos/message/`
- `python/apps/azents/src/azents/rdb/models/event.py`
- `python/apps/azents/src/azents/rdb/models/agent_session.py`
- `python/apps/azents/src/azents/rdb/models/agent_run.py`
- `python/apps/azents/src/azents/services/input_buffer_promotion.py`
- `python/apps/azents/db-schemas/rdb/migrations/versions/29d80393ae0e_cut_over_canonical_runtime_tables.py`
- `testenv/azents/e2e/src/tests/azents/public/`

All verdict values in this document are `fully applied`. However, provider hosted tool stabilization, which ADR explicitly split as non-blocking, remains tracked in #4100. It is not a condition blocking completion of [execution-260527/ADR](../adr/execution-260527-execution-transcript-normalization.md) canonical runtime cutover.

## Prerequisite Handling

There were three items with prerequisites during ADR application.

First, existing `events`, `agent_sessions` remained before final table cutover. This PR added destructive migration that discards existing legacy tables and converts `events_next`, `agent_sessions_next`, `agent_runs_next` into `events`, `agent_sessions`, `agent_runs` respectively. To avoid conflict with test fixture requirement for downgrade-to-base, downgrade path includes compatibility path that temporarily recreates legacy shape. Durable source of truth in production upgrade path is single canonical schema.

Second, REST history was reading legacy event envelope. `MessageRepository` now projects canonical events directly into `ChatMessage` for user/assistant/reasoning/tool/provider/marker/subagent/system events.

Third, input buffer flush was appending only to legacy `EventStore`. Flush path now appends canonical `user_message` in same transaction. Legacy `EventStore` remains only as transient stream projection compatibility and does not write to DB.

Fourth, manual compaction E2E did not use summary mock endpoint and could leave actual OpenAI endpoint 401 in logs. Compaction summary call also normalizes Responses endpoint kwargs to follow `AZ_OPENAI_BASE_URL` and ChatGPT OAuth endpoint policy, and summary failure is propagated to caller instead of hidden as `compaction_complete`.

## Design Contradiction Review

No blocker-level design contradiction between [execution-260527/ADR](../adr/execution-260527-execution-transcript-normalization.md) and implementation was found.

One point to be careful about is migration downgrade. ADR allows destructive cutover because this is private service, but local pytest fixture runs `downgrade base`. This is not product requirement contradiction but test infrastructure requirement. Therefore, upgrade remains destructive, and downgrade only has old-shape recreation for test teardown.

## ADR Item-by-item Application Status

### 1. Use canonical transcript as durable source of truth

Verdict: fully applied.

Final `events` table became canonical `kind/payload/native metadata` schema. Shadow table names are removed in migration. `repos/message` also directly reads canonical transcript. `RDBEventStore` is in-memory compatibility wrapper, not DB write path.

### 2. Adapter boundary is bidirectional

Verdict: fully applied.

LiteLLM Responses path is separated into lowerer, model adapter, and output normalizer. Canonical core does not interpret adapter-native payload.

### 3. SDK Runner is not final loop owner

Verdict: fully applied.

`AgentRunExecution` owns model step, streaming, normalization, tool execution, append, and next-step loop. OpenAI Agents SDK production path has been removed.

### 4. Target clean-state replacement

Verdict: fully applied.

Legacy raw `runtime/llm.py`, SDK runtime source, SDK RunState durable column, and legacy durable event table path were removed from production source of truth.

### 5. Drop reasoning in cross-model lowering

Verdict: fully applied.

Reasoning is preserved as canonical `reasoning` event. Cross-model lowerer does not convert reasoning text and summary into assistant/user/system content.

### 6. Canonical user_message payload

Verdict: fully applied.

`user_message` has only `content`, `attachments`, `metadata`. Both input buffer flush and runtime append path store canonical payload.

### 7. Canonical assistant_message payload

Verdict: fully applied.

Assistant output is stored as `assistant_message`, and REST projection directly reads canonical attachment and content.

### 8. Canonical reasoning payload

Verdict: fully applied.

`text`, `summary`, and `native_artifact` are separated, and UI/audit projection uses canonical reasoning.

### 9. Separate system reminder and system error

Verdict: fully applied.

Canonical payload separates `system_reminder` and `system_error`. REST projection excludes reminder from history display and projects error as assistant-visible failure message.

### 10. Represent tool call/result as common canonical events

Verdict: fully applied.

Client/provider tool call and result are both stored as canonical event kinds. Generated image is displayed as provider tool result projection. Hosted tool stabilization itself is in #4100 scope.

### 11. Store canonical tool result as part array

Verdict: fully applied.

Both client/provider tool results use `output_*` part array and status. Client result has no native artifact, and provider result has native artifact.

### 12. Tool loop semantics

Verdict: fully applied.

Foreground tool execution, failed result repair, active tool call projection, stop/interrupted status path are connected to canonical execution loop and `agent_runs` state.

### 13. Attachment is payload-specific

Verdict: fully applied.

Attachment is inside user/assistant/tool result payload, not event-common field. REST projection also reads attachment by payload.

### 14. Unify attachment rendering with manifest

Verdict: fully applied.

Model input lowerer/filter boundary handles attachment rendering, and durable canonical payload preserves attachment ref and metadata. Screen projection lowers canonical attachment snapshot to REST attachment.

### 15. Make generated image/file into artifact at output normalizer stage

Verdict: fully applied.

LiteLLM Responses normalizer raises generated image output as provider tool result and attachment-bearing output part. Actual stabilization of provider hosted tool continues to be tracked in #4100.

### 16. Builtin/provider tool policy

Verdict: fully applied.

Unsupported provider tool is controlled by post-lower/filter policy. Actual hosted tool support was decided non-blocking in ADR and split to #4100.

### 17. Store generated output origin in DB canonical event within size limit

Verdict: fully applied.

Canonical event payload stores generated output part and native artifact separately. Provider payload size/failure detailed policy remains as implementation unit inside adapter/output normalizer boundary and does not conflict with source-of-truth decision.

### 18. Split model input build into pre-filter, adapter lowerer, post-filter

Verdict: fully applied.

Pre-lower filter, adapter-specific lowerer, post-lower filter, model adapter, and output normalizer boundaries are reflected in code.

### 19. Capability-based unsupported modality conversion is lowerer responsibility

Verdict: fully applied.

Unsupported modality degrade is responsibility of adapter lowerer/filter boundary. Generic request IR was not introduced.

### 20. Compaction is append-only and moves model_input_head_event_id

Verdict: fully applied.

Compaction appends `compaction_marker` and `compaction_summary` and moves `agent_sessions.model_input_head_event_id` to summary event id. Canonical compaction path does not delete old events.

### 21. Preserve existing compaction timing and policy

Verdict: fully applied.

Manual compact and model input head semantics share canonical compactor primitive. Auto trigger is connected as pre-model-call policy, and durable mutation primitive is unified as canonical.

### 22. Connect compaction lifecycle with compaction_id

Verdict: fully applied.

Both marker and summary payload have `compaction_id` and represent same compaction lifecycle.

### 23. Split subagent lifecycle into start/end events

Verdict: fully applied.

Canonical event kind and REST projection separate `subagent_start` / `subagent_end` and connect with `subagent_run_id`.

### 24. Marker payload

Verdict: fully applied.

`turn_marker`, `run_marker`, `compaction_marker`, `compaction_summary`, `subagent_start`, `subagent_end` payloads have ADR fields. REST projection reads run/turn/compaction/subagent marker from canonical event.

### 25. Streaming delta is not durable canonical event

Verdict: fully applied.

Streaming delta is used only as UI projection. Durable canonical event is appended after completed output normalization.

### 26. Keep Azents-owned RunExecutionState

Verdict: fully applied.

Final `agent_runs` table and `AgentRunRepository` store durable run state. Phase is enum usable as UI activity source and includes active tool calls. SDK RunState column is removed by drop migration.

## Verification

Verified locally with:

- `uv run pyright .`
- `uv run pytest src/azents/repos/agent_execution/repository_test.py src/azents/services/chat/input_buffer_test.py src/azents/services/input_buffer_promotion_test.py -q`
- `uv run pytest src/azents/runtime/canonical/execution_test.py src/azents/runtime/canonical/legacy_projection_test.py src/azents/runtime/canonical/tools_test.py src/azents/engine/events/store_test.py -q`
- `cd testenv/azents/e2e && uv run pyright . && uv run pytest src/tests/azents/public/test_agent_execution_persistence.py src/tests/azents/public/test_file_upload.py::TestUploadMessagePath::test_image_and_file_uploads_reach_model_input -v -s`
- `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
- `git diff --check`

Regression found during testing was that REST history became empty because input buffer flush did not remain in canonical `events`. Fixed `InputBufferPromotionService` to append canonical `user_message` and reverified.

Additional regression found was canonical runner could re-append input buffer external id and cause `uq_events_session_external` unique violation. Fixed runner append path to dedupe by external id and cleaned up user message content not to mix metadata. Attachment context is rendered only as model-visible input part in LiteLLM Responses lowerer, not durable content.
