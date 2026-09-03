"use client";

/**
 * Agent create/update page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentFormContainer } from "./containers/AgentFormContainer";
import { useAgentFormContainer } from "./containers/useAgentFormContainer";

export const AgentFormPage = createReactContainer(
  "AgentFormPage",
  useAgentFormContainer,
  AgentFormContainer,
);
