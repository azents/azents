export interface FailedDraftSessionWriteRequest {
  key: string;
  id: string;
}

export interface DraftSessionWriteSemantics {
  agentId: string;
  message: string;
  inferenceProfile: unknown;
  attachments: readonly string[];
  existingProjectPaths: readonly string[];
  setupActions: readonly unknown[];
}

/** Serialize exactly the client-controlled semantics guarded by the backend. */
export function draftSessionWriteKey(
  semantics: DraftSessionWriteSemantics,
): string {
  return JSON.stringify(semantics);
}

/** Reuse an ID only for a retry of the exact failed semantic write. */
export function clientRequestIdForDraftSessionWrite(
  failed: FailedDraftSessionWriteRequest | null,
  writeKey: string,
  createClientRequestId: () => string,
): string {
  if (failed?.key === writeKey) {
    return failed.id;
  }
  return createClientRequestId();
}
