"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceRuntimeExecution } from "./components/WorkspaceRuntimeExecution";
import { useWorkspaceRuntimeExecutionContainer } from "./containers/useWorkspaceRuntimeExecutionContainer";

export const WorkspaceRuntimeExecutionPage = createReactContainer(
  "WorkspaceRuntimeExecutionPage",
  useWorkspaceRuntimeExecutionContainer,
  WorkspaceRuntimeExecution,
);
