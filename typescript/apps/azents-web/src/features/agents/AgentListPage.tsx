"use client";

/**
 * Agent list page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentList } from "./components/AgentList";
import { useAgentListContainer } from "./containers/useAgentListContainer";

export const AgentListPage = createReactContainer(
  "AgentListPage",
  useAgentListContainer,
  AgentList,
);
