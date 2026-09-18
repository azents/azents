export const WORKSPACE_UPLOAD_STATUS_FETCH_OPTIONS = {
  staleTime: 0,
} as const;

export interface WorkspaceUploadStatusQueryInput {
  agentId: string;
  uploadId: string;
}

export type WorkspaceUploadStatusQueryFetcher<TStatus> = (
  input: WorkspaceUploadStatusQueryInput,
  options: typeof WORKSPACE_UPLOAD_STATUS_FETCH_OPTIONS,
) => Promise<TStatus>;

export interface PollWorkspaceUploadStatusInput<TStatus> {
  fetchStatus: WorkspaceUploadStatusQueryFetcher<TStatus>;
  input: WorkspaceUploadStatusQueryInput;
  isTerminal: (status: TStatus) => boolean;
  onStatus: (status: TStatus) => void | Promise<void>;
  wait: () => Promise<void>;
  shouldStop?: () => boolean;
}

/**
 * Poll a workspace upload until the server reports a terminal phase.
 *
 * The explicit `staleTime: 0` is required because the web QueryClient uses a
 * five-minute default stale time. Upload lifecycle status is mutable on the
 * server, so every poll must issue a fresh request rather than reuse cache.
 */
export async function pollWorkspaceUploadStatus<TStatus>({
  fetchStatus,
  input,
  isTerminal,
  onStatus,
  wait,
  shouldStop,
}: PollWorkspaceUploadStatusInput<TStatus>): Promise<TStatus | null> {
  for (;;) {
    if (shouldStop?.()) {
      return null;
    }

    const status = await fetchStatus(
      input,
      WORKSPACE_UPLOAD_STATUS_FETCH_OPTIONS,
    );
    await onStatus(status);
    if (isTerminal(status)) {
      return status;
    }
    await wait();
  }
}
