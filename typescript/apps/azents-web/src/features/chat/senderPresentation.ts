/** Human sender provenance presentation without identity inference. */

export interface CurrentWorkspaceProfile {
  userId: string;
  name: string;
}

export type HumanSenderPresentation =
  | { type: "AVAILABLE"; name: string }
  | { type: "UNAVAILABLE" };

export function humanSenderPresentation(
  senderUserId: string | null,
  currentWorkspaceProfile: CurrentWorkspaceProfile | null,
): HumanSenderPresentation {
  if (
    senderUserId === null ||
    currentWorkspaceProfile === null ||
    currentWorkspaceProfile.userId !== senderUserId
  ) {
    return { type: "UNAVAILABLE" };
  }

  const name = currentWorkspaceProfile.name.trim();
  return name ? { type: "AVAILABLE", name } : { type: "UNAVAILABLE" };
}
