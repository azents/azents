const MAX_AUTO_ARCHIVE_WARNING_DAYS = 5;
const DAY_MS = 24 * 60 * 60 * 1000;

export function autoArchiveWarningDays(ttlDays: number): number {
  return Math.min(Math.floor(ttlDays / 2), MAX_AUTO_ARCHIVE_WARNING_DAYS);
}

export function isAutoArchiveDueSoon(
  autoArchiveAfter: string | null,
  ttlDays: number,
  nowMs: number = Date.now(),
): boolean {
  const warningDays = autoArchiveWarningDays(ttlDays);
  if (warningDays === 0 || autoArchiveAfter === null) {
    return false;
  }

  const autoArchiveAfterMs = Date.parse(autoArchiveAfter);
  if (Number.isNaN(autoArchiveAfterMs)) {
    return false;
  }

  return autoArchiveAfterMs <= nowMs + warningDays * DAY_MS;
}
