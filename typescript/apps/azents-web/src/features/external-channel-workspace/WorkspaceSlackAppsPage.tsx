"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceSlackApps } from "./components/WorkspaceSlackApps";
import { useWorkspaceSlackAppsContainer } from "./containers/useWorkspaceSlackAppsContainer";

export const WorkspaceSlackAppsPage = createReactContainer(
  "WorkspaceSlackAppsPage",
  useWorkspaceSlackAppsContainer,
  WorkspaceSlackApps,
);
