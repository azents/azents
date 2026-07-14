const DURATION_VISIBILITY_THRESHOLD_SECONDS = 10;
const DURATION_REFRESH_INTERVAL_MS = 1000;

type SetInterval = (callback: () => void, delay: number) => number;
type ClearInterval = (timerId: number) => void;

function timestampMs(iso: string): number | null {
  const value = new Date(iso).getTime();
  return Number.isFinite(value) ? value : null;
}

export function visibleModelCallDurationSeconds(
  startedAt: string | null,
  nowMs: number,
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
  return durationSeconds >= DURATION_VISIBILITY_THRESHOLD_SECONDS
    ? durationSeconds
    : null;
}

export function startModelCallDurationTimer(
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
