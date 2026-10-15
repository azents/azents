"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentWorkspaceEnvironmentSelection } from "./components/AgentWorkspaceEnvironmentSelection";
import { useAgentWorkspaceEnvironmentSelection } from "./containers/useAgentWorkspaceEnvironmentSelection";

export const AgentWorkspaceEnvironmentSection = createReactContainer(
  "AgentWorkspaceEnvironmentSection",
  useAgentWorkspaceEnvironmentSelection,
  AgentWorkspaceEnvironmentSelection,
);
