import type { ChatEventResponse } from "@azents/public-client";

export interface RunActivityProjection {
  liveRun: unknown;
  liveRunPhase: unknown;
  sessionRunState: "idle" | "running";
  isResponsePending: boolean;
  isCompacting: boolean;
}

export function applyStoppedRunProjection<State extends RunActivityProjection>(
  state: State,
): State {
  return {
    ...state,
    liveRun: null,
    liveRunPhase: null,
    sessionRunState: "idle",
    isResponsePending: false,
    isCompacting: false,
  };
}

export function restoreRunActivityProjection<
  State extends RunActivityProjection,
>(current: State, previous: State): State {
  return {
    ...current,
    liveRun: previous.liveRun,
    liveRunPhase: previous.liveRunPhase,
    sessionRunState: previous.sessionRunState,
    isResponsePending: previous.isResponsePending,
    isCompacting: previous.isCompacting,
  };
}

export function liveActivityResponsePending(
  current: boolean,
  activityWaitsForResponse: boolean,
  optimisticStopActive: boolean,
): boolean {
  return optimisticStopActive ? false : current || activityWaitsForResponse;
}

export function interruptedEventExternalId(runId: string): string {
  return `interrupted:${runId}:user_requested`;
}

export function createOptimisticInterruptedEvent(
  sessionId: string,
  runId: string,
  createdAt: string,
): ChatEventResponse {
  const externalId = interruptedEventExternalId(runId);
  return {
    id: `optimistic:${externalId}`,
    session_id: sessionId,
    kind: "interrupted",
    payload: { run_id: runId, reason: "user_requested" },
    model_order: 0,
    external_id: externalId,
    adapter: null,
    provider: null,
    model: null,
    native_format: null,
    schema_version: "1",
    created_at: createdAt,
  };
}

interface LivePartialEventIdentity {
  kind: string;
  payload: Record<string, unknown>;
}

export function eventInterruptsRun(
  event: LivePartialEventIdentity,
  runId: string,
): boolean {
  return event.kind === "interrupted" && event.payload.run_id === runId;
}

export function shouldProjectLivePartialEvent(
  event: LivePartialEventIdentity,
  optimisticStopRunId: string | null,
): boolean {
  return (
    optimisticStopRunId === null ||
    eventInterruptsRun(event, optimisticStopRunId)
  );
}
