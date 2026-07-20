const DURATION_REFRESH_INTERVAL_MS = 1_000;

type SetInterval = (callback: () => void, delay: number) => number;
type ClearInterval = (timerId: number) => void;

function timestampMs(iso: string): number | null {
  const value = new Date(iso).getTime();
  return Number.isFinite(value) ? value : null;
}

export function visibleElapsedDurationSeconds(
  startedAt: string | null,
  nowMs: number,
  visibilityThresholdSeconds: number,
): number | null {
  if (startedAt === null) {
    return null;
  }
  const startedAtMs = timestampMs(startedAt);
  if (startedAtMs === null) {
    return null;
  }
  const durationSeconds = Math.max(
    0,
    Math.floor((nowMs - startedAtMs) / DURATION_REFRESH_INTERVAL_MS),
  );
  return durationSeconds >= visibilityThresholdSeconds ? durationSeconds : null;
}

export function formatElapsedDuration(durationSeconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(durationSeconds));
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function startElapsedDurationTimer(
  startedAt: string | null,
  onTick: () => void,
  setInterval: SetInterval,
  clearInterval: ClearInterval,
): () => void {
  const timerId =
    startedAt !== null && timestampMs(startedAt) !== null
      ? setInterval(onTick, DURATION_REFRESH_INTERVAL_MS)
      : null;
  return () => {
    if (timerId !== null) {
      clearInterval(timerId);
    }
  };
}
