export function infrastructureProfileDeletionFailureMessage(
  message: string,
): string {
  try {
    const detail: unknown = JSON.parse(message);
    if (
      typeof detail === "object" &&
      detail !== null &&
      "code" in detail &&
      typeof detail.code === "string"
    ) {
      switch (detail.code) {
        case "profile_version_conflict":
          return "The Profile changed. Review the refreshed impact before deleting.";
        case "profile_referenced":
          return "A current Workspace Runtime Profile now references this Profile.";
        case "profile_not_found":
          return "The Profile was already deleted or is no longer available.";
        case "profile_delete_conflict":
          return "Deletion conflicted with a concurrent reference. Review current impact and retry.";
      }
    }
  } catch {
    return message;
  }
  return message;
}

export function previousDeletionReferenceOffset(
  offset: number,
  limit: number,
): number {
  return Math.max(0, offset - limit);
}

export function nextDeletionReferenceOffset(
  offset: number,
  limit: number,
  returnedCount: number,
  totalCount: number,
): number {
  return offset + returnedCount < totalCount ? offset + limit : offset;
}

export function infrastructureProfileDeletionConfirmationEnabled({
  refreshPending,
  impactError,
  blockingReferenceCount,
}: {
  refreshPending: boolean;
  impactError: boolean;
  blockingReferenceCount?: number;
}): boolean {
  return !refreshPending && !impactError && blockingReferenceCount === 0;
}
