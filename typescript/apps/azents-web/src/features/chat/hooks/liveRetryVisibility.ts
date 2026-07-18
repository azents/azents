import type { ChatLiveRunState } from "../types";

export function liveRetryDisplayKey(
  liveRun: ChatLiveRunState | null,
): string | null {
  if (liveRun === null || liveRun.retry == null) {
    return null;
  }
  return `${liveRun.run_id}:${liveRun.retry.failedAttemptCount}`;
}

export function resolveDismissedLiveRetryKey(
  liveRun: ChatLiveRunState | null,
  previousDismissedRetryKey: string | null,
  streamingProgressObserved: boolean,
): string | null {
  const currentRetryKey = liveRetryDisplayKey(liveRun);
  if (currentRetryKey === null) {
    return null;
  }
  if (streamingProgressObserved) {
    return currentRetryKey;
  }
  return previousDismissedRetryKey === currentRetryKey
    ? previousDismissedRetryKey
    : null;
}

export function liveRunForDisplay(
  liveRun: ChatLiveRunState | null,
  dismissedRetryKey: string | null,
): ChatLiveRunState | null {
  if (
    liveRun === null ||
    dismissedRetryKey === null ||
    liveRetryDisplayKey(liveRun) !== dismissedRetryKey
  ) {
    return liveRun;
  }
  return { ...liveRun, retry: null };
}
