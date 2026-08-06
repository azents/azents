"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSessionDirectory } from "./components/AgentSessionDirectory";
import { useAgentSessionDirectoryContainer } from "./containers/useAgentSessionDirectoryContainer";

export const AgentSessionDirectoryPage = createReactContainer(
  "AgentSessionDirectoryPage",
  useAgentSessionDirectoryContainer,
  AgentSessionDirectory,
);
