"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentRuntimeEnvironmentVariables } from "@/shared/runtime-environment/AgentRuntimeEnvironmentVariables";
import { useAgentRuntimeEnvironmentVariablesContainer } from "./containers/useAgentRuntimeEnvironmentVariablesContainer";

export const AgentRuntimeEnvironmentVariablesSection = createReactContainer(
  "AgentRuntimeEnvironmentVariablesSection",
  useAgentRuntimeEnvironmentVariablesContainer,
  AgentRuntimeEnvironmentVariables,
);
