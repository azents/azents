"use client";

/**
 * Agent Chat tab entry.
 *
 * Connects Container hook and UI component with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentChatTab } from "./components/AgentChatTab";
import { useAgentChatContainer } from "./containers/useAgentChatContainer";

export const AgentChatTabPage = createReactContainer(
  "AgentChatTabPage",
  useAgentChatContainer,
  AgentChatTab,
);
