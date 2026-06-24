"use client";

/**
 * Workspace creation container
 *
 * Authenticated user creates new workspace.
 * Move to dashboard on success.
 */
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { WorkspaceCreateState } from "../types";

export interface WorkspaceCreateContainerProps {
  state: WorkspaceCreateState;
  onSubmit: (data: {
    workspaceName: string;
    workspaceHandle: string;
    ownerName: string;
  }) => void;
}

export function useWorkspaceCreate(): WorkspaceCreateContainerProps {
  const router = useRouter();
  const utils = trpc.useUtils();

  const createMutation = trpc.workspace.create.useMutation({
    onSuccess: (data) => {
      void utils.workspace.list.invalidate();
      router.push(`/w/${data.workspace_handle}`);
    },
  });

  const state: WorkspaceCreateState = createMutation.isPending
    ? { type: "CREATING" }
    : { type: "IDLE", error: createMutation.error?.message ?? null };

  const onSubmit = useCallback(
    (data: {
      workspaceName: string;
      workspaceHandle: string;
      ownerName: string;
    }) => {
      createMutation.mutate(data);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- createMutation is new reference every render
    [],
  );

  return { state, onSubmit };
}
