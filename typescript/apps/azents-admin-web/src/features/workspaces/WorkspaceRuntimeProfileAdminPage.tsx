"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceRuntimeProfileAdminView } from "./components/WorkspaceRuntimeProfileAdminView";
import { useWorkspaceRuntimeProfileAdminContainer } from "./containers/useWorkspaceRuntimeProfileAdminContainer";
import type { WorkspaceRuntimeProfileAdminContainerProps } from "./containers/useWorkspaceRuntimeProfileAdminContainer";

export const WorkspaceRuntimeProfileAdminPage = createReactContainer<
  WorkspaceRuntimeProfileAdminContainerProps,
  ReturnType<typeof useWorkspaceRuntimeProfileAdminContainer>
>(
  "WorkspaceRuntimeProfileAdminPage",
  useWorkspaceRuntimeProfileAdminContainer,
  WorkspaceRuntimeProfileAdminView,
);
