"use client";

/**
 * Agent avatar upload container — 3-step presigned flow.
 *
 * 1. Obtain presigned PUT URL with `requestAvatarUpload` mutation
 * 2. Directly call `fetch(url, { method: "PUT", body: file })` on that URL
 * 3. Request server validation/publish with `finalizeAvatar` mutation
 * 4. On completion, invalidate agent get/list cache → UI renders new thumbnail
 *
 * Errors for each step are exposed as ADT State. Component renders only state-specific UX.
 */

import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";

const ALLOWED_MIME = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_BYTES = 5 * 1024 * 1024;

export type AvatarUploadState =
  | { type: "idle" }
  | { type: "validating" }
  | { type: "requesting-url" }
  | { type: "uploading" }
  | { type: "finalizing" }
  | { type: "removing" }
  | { type: "error"; message: string };

interface UseAgentAvatarContainer {
  handle: string;
  agentId: string;
}

/** Client pre-validates image is square and within allowed size range. */
async function validateSquare(file: File): Promise<void> {
  if (!ALLOWED_MIME.has(file.type)) {
    throw new Error("Only JPEG, PNG, or WebP images are allowed.");
  }
  if (file.size <= 0 || file.size > MAX_BYTES) {
    throw new Error("Image size must be between 1 byte and 5 MB.");
  }
  const bitmap = await createImageBitmap(file);
  try {
    if (bitmap.width !== bitmap.height) {
      throw new Error("Image must be square.");
    }
    if (bitmap.width > 4096) {
      throw new Error("Image dimension must be 4096 pixels or smaller.");
    }
  } finally {
    bitmap.close();
  }
}

export function useAgentAvatarContainer({
  handle,
  agentId,
}: UseAgentAvatarContainer): {
  state: AvatarUploadState;
  uploadFile: (file: File) => Promise<void>;
  removeAvatar: () => Promise<void>;
  reset: () => void;
} {
  const [state, setState] = useState<AvatarUploadState>({ type: "idle" });
  const utils = trpc.useUtils();
  const requestMutation = trpc.agent.requestAvatarUpload.useMutation();
  const finalizeMutation = trpc.agent.finalizeAvatar.useMutation();
  const removeMutation = trpc.agent.removeAvatar.useMutation();

  const invalidate = useCallback(() => {
    void utils.agent.get.invalidate({ handle, agentId });
    void utils.agent.list.invalidate({ handle });
  }, [utils, handle, agentId]);

  const uploadFile = useCallback(
    async (file: File): Promise<void> => {
      try {
        setState({ type: "validating" });
        await validateSquare(file);

        setState({ type: "requesting-url" });
        const ticket = await requestMutation.mutateAsync({
          handle,
          agentId,
          contentType: file.type,
          contentLength: file.size,
        });

        setState({ type: "uploading" });
        const putResponse = await fetch(ticket.upload_url, {
          method: "PUT",
          headers: { "Content-Type": file.type },
          body: file,
        });
        if (!putResponse.ok) {
          throw new Error(`Upload failed (${putResponse.status}).`);
        }

        setState({ type: "finalizing" });
        await finalizeMutation.mutateAsync({
          handle,
          agentId,
          uploadKey: ticket.upload_key,
          filename: file.name,
        });

        invalidate();
        setState({ type: "idle" });
      } catch (err) {
        const message = err instanceof Error ? err.message : "Upload failed.";
        setState({ type: "error", message });
      }
    },
    [handle, agentId, requestMutation, finalizeMutation, invalidate],
  );

  const removeAvatar = useCallback(async (): Promise<void> => {
    try {
      setState({ type: "removing" });
      await removeMutation.mutateAsync({ handle, agentId });
      invalidate();
      setState({ type: "idle" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Remove failed.";
      setState({ type: "error", message });
    }
  }, [handle, agentId, removeMutation, invalidate]);

  const reset = useCallback((): void => {
    setState({ type: "idle" });
  }, []);

  return { state, uploadFile, removeAvatar, reset };
}
