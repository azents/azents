"use client";

import { useConfig } from "@/config/client";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";
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
  workspacesPath: string;
}

export function useWorkspaceRuntimeProfileAdminContainer({
  workspaceHandle,
  profileId,
}: WorkspaceRuntimeProfileAdminContainerProps): WorkspaceRuntimeProfileAdminComponentProps {
  const { publicBaseUrl } = useConfig();
  const workspacesPath = getPublicRoutePath(publicBaseUrl, "/workspaces");
  const detailQuery =
    trpc.runtimeProvider.getWorkspaceProfileAdminDetail.useQuery(
      { workspaceHandle, profileId },
      { retry: false },
    );
  if (detailQuery.isLoading) {
    return { state: { type: "LOADING" }, workspacesPath };
  }
  if (detailQuery.isError) {
    return {
      workspacesPath,
      state:
        detailQuery.error.data?.code === "NOT_FOUND"
          ? { type: "NOT_FOUND" }
          : { type: "ERROR", message: detailQuery.error.message },
    };
  }
  if (detailQuery.data == null) {
    return { state: { type: "LOADING" }, workspacesPath };
  }
  return {
    workspacesPath,
    state: { type: "LOADED", detail: detailQuery.data },
  };
}
