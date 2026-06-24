---
title: "Runtime runner stalls after tool result"
created: 2026-06-10
tags: [runtime, backend, chat, incident]
---

# Runtime runner stalls after tool result

## Summary

Around 2026-06-10 11:33 KST, chat context showed a stall symptom where the next assistant step did not proceed after `CLIENT_TOOL_RESULT`. Execution was still not continuing when user checked at 2026-06-10 11:53 KST.

This issue is not in scope of current FE follow/scroll/resume buffering fix PR. That PR only records this and continues as separate backend/runtime research.

## Observed Symptoms

- In session context screen, last event was stopped around 2026-06-10 11:33 KST.
- After `CLIENT_TOOL_CALL`, `TURN_MARKER`, and `CLIENT_TOOL_RESULT` were recorded, it did not proceed to next assistant message or next tool call.
- There were no additional events at 2026-06-10 11:53 KST.
- This is not a 30-second periodic reconcile issue. Reconcile only re-reads already persisted context as normal recovery/query path, and this is a separate problem where run progression itself did not continue.

## Production Log Snapshot

At time of investigation, production logs showed likely same session with `session_id=689ece9578e54f71be7fbe881eadff4e`.

- `azents-server/worker-65497bdd47-d7qms`
  - 2026-06-10T02:53:58Z: `Starting session runner`, `session_id=689ece9578e54f71be7fbe881eadff4e`
- `azents-runtime/azents-runtime-c28355245d77440498fc216a7e6c0684`
  - 2026-06-10T02:33:41Z: Runtime Runner Control stream disconnected
  - stack: `RuntimeRunnerControlStreamClosed: Runner Control stream is closed`
  - 2026-06-10T02:33:42Z: Runtime Runner reconnected/registered
  - After 2 operation claimed logs at 2026-06-10T02:33:42Z, next operation claimed is not visible until 2026-06-10T02:53:07Z

02:33Z is 11:33 KST and matches last event time observed by user.

## Current Hypotheses

1. Accepted operation or run continuation state may have been lost at Runtime runner control stream disconnect/reconnect time.
2. After `CLIENT_TOOL_RESULT`, engine worker may not have enqueued next model step, or enqueued it but claim/ack state got inconsistent in runtime/control side.
3. Recovery path for resuming orphaned in-flight operation after runner generation stale/stream closed handling may be insufficient.
4. FE only queries context/history and shows last persisted event, so it is likely not direct cause of this symptom.

## Next Research Items

- Confirm the session/run id based on DB.
- Compare `agent_runs`, operation queue/control tables, and session event tail.
- Check whether next engine transition was created after `CLIENT_TOOL_RESULT` persistence.
- Check whether accepted operation redelivery/resume is guaranteed on runtime runner control stream disconnect.
- Check whether stale active run cleanup or retry path exists after worker restart/runner reconnect.

## Out of Scope

- Do not fix this backend/runtime stall in current FE follow/scroll/resume buffering PR.
- 30-second periodic reconcile is not considered the cause.
