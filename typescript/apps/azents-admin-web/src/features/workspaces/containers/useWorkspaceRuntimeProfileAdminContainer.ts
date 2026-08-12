"use client";

import { trpc } from "@/trpc/client";
import type { AdminWorkspaceRuntimeProfileDetailResponse } from "@azents/admin-client";

export type WorkspaceRuntimeProfileAdminState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; detail: AdminWorkspaceRuntimeProfileDetailResponse };

export interface WorkspaceRuntimeProfileAdminContainerProps {
  workspaceHandle: string;
  profileId: string;
}

export interface WorkspaceRuntimeProfileAdminComponentProps {
  state: WorkspaceRuntimeProfileAdminState;
}

export function useWorkspaceRuntimeProfileAdminContainer({
  workspaceHandle,
  profileId,
}: WorkspaceRuntimeProfileAdminContainerProps): WorkspaceRuntimeProfileAdminComponentProps {
  const detailQuery =
    trpc.runtimeProvider.getWorkspaceProfileAdminDetail.useQuery(
      {
        workspaceHandle,
        profileId,
      },
      { retry: false },
    );

  if (detailQuery.isLoading) {
    return { state: { type: "LOADING" } };
  }
  if (detailQuery.isError) {
    return {
      state:
        detailQuery.error.data?.code === "NOT_FOUND"
          ? { type: "NOT_FOUND" }
          : { type: "ERROR", message: detailQuery.error.message },
    };
  }
  if (detailQuery.data == null) {
    return { state: { type: "LOADING" } };
  }
  return {
    state: {
      type: "LOADED",
      detail: detailQuery.data,
    },
  };
}
