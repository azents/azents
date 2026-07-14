export function canApplyRunStartedEvent(
  activeRunId: string | null,
  terminatedRunIds: readonly string[],
  eventRunId: string,
): boolean {
  return (
    activeRunId === eventRunId ||
    (activeRunId === null && !terminatedRunIds.includes(eventRunId))
  );
}

export function canApplyRunActivityEvent(
  activeRunId: string | null,
  eventRunId: string,
): boolean {
  return activeRunId === eventRunId;
}

export interface CanonicallyOrderedHistoryEvent {
  id: string;
  model_order: number;
}

/** Upsert one durable event using the backend's canonical timeline order. */
export function upsertCanonicalHistoryEvent<
  T extends CanonicallyOrderedHistoryEvent,
>(events: readonly T[], event: T): T[] {
  const index = events.findIndex((item) => item.id === event.id);
  const next =
    index < 0
      ? [...events, event]
      : events.map((item, itemIndex) => (itemIndex === index ? event : item));
  return next.sort(
    (left, right) =>
      left.model_order - right.model_order ||
      (left.id < right.id ? -1 : left.id > right.id ? 1 : 0),
  );
}

export function canAdoptLiveRunUpdatedEvent(
  activeRunId: string | null,
  terminatedRunIds: readonly string[],
  eventRunId: string,
): boolean {
  return (
    activeRunId === eventRunId ||
    (activeRunId === null && !terminatedRunIds.includes(eventRunId))
  );
}

export function canApplyAuthoritativeRunSnapshot(
  activeRunId: string | null,
  terminatedRunIds: readonly string[],
  snapshotRunId: string,
): boolean {
  return (
    activeRunId === snapshotRunId || !terminatedRunIds.includes(snapshotRunId)
  );
}

export function rememberTerminatedRunId(
  terminatedRunIds: readonly string[],
  runId: string,
): string[] {
  return [
    ...terminatedRunIds.filter((candidate) => candidate !== runId),
    runId,
  ];
}

export interface AuthoritativeRunIdentity {
  applySnapshot: boolean;
  activeRunId: string | null;
  terminatedRunIds: string[];
}

export type AuthoritativeRunIdentitySnapshot =
  | { type: "INVALID" }
  | { type: "ABSENT" }
  | { type: "PRESENT"; runId: string; isRunning: boolean };

/**
 * Reconcile an authoritative REST run snapshot with buffered WebSocket state.
 * A present non-running snapshot is terminal and must never become active.
 */
export function reconcileAuthoritativeRunIdentity(
  activeRunId: string | null,
  terminatedRunIds: readonly string[],
  snapshot: AuthoritativeRunIdentitySnapshot,
): AuthoritativeRunIdentity {
  if (snapshot.type === "INVALID") {
    return {
      applySnapshot: false,
      activeRunId,
      terminatedRunIds: [...terminatedRunIds],
    };
  }

  if (snapshot.type === "ABSENT") {
    return {
      applySnapshot: true,
      activeRunId: null,
      terminatedRunIds:
        activeRunId === null
          ? [...terminatedRunIds]
          : rememberTerminatedRunId(terminatedRunIds, activeRunId),
    };
  }

  const snapshotRunId = snapshot.runId;
  if (!snapshot.isRunning) {
    const nextTerminatedRunIds = rememberTerminatedRunId(
      terminatedRunIds,
      snapshotRunId,
    );
    if (activeRunId !== null && activeRunId !== snapshotRunId) {
      return {
        applySnapshot: false,
        activeRunId,
        terminatedRunIds: nextTerminatedRunIds,
      };
    }
    return {
      applySnapshot: true,
      activeRunId: null,
      terminatedRunIds: nextTerminatedRunIds,
    };
  }

  if (
    !canApplyAuthoritativeRunSnapshot(
      activeRunId,
      terminatedRunIds,
      snapshotRunId,
    )
  ) {
    return {
      applySnapshot: false,
      activeRunId,
      terminatedRunIds: [...terminatedRunIds],
    };
  }

  return {
    applySnapshot: true,
    activeRunId: snapshotRunId,
    terminatedRunIds:
      activeRunId === null || activeRunId === snapshotRunId
        ? [...terminatedRunIds]
        : rememberTerminatedRunId(terminatedRunIds, activeRunId),
  };
}

export function canApplyRunTerminalEvent(
  activeRunId: string | null,
  eventRunId: string,
): boolean {
  return activeRunId === eventRunId;
}

export type StopReconciliationSnapshot =
  | { type: "NOT_APPLIED" }
  | { type: "APPLIED"; activeRunId: string | null };

/** Keep reconciling until a REST snapshot confirms the stopped Run is terminal. */
export function shouldContinueStopReconciliation(
  stoppedRunId: string,
  snapshot: StopReconciliationSnapshot,
  remainingAttempts: number,
  remainingTimeMs: number,
): boolean {
  return (
    remainingAttempts > 0 &&
    remainingTimeMs > 0 &&
    (snapshot.type === "NOT_APPLIED" || snapshot.activeRunId === stoppedRunId)
  );
}
