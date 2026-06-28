"use client";

/**
 * Agent draft chat entry.
 *
 * Shows a chat-only draft state before an AgentSession exists. The first
 * successful message creates the concrete session and replaces the URL.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentDraftChat } from "./components/AgentDraftChat";
import { useAgentDraftChatContainer } from "./containers/useAgentDraftChatContainer";

export const AgentDraftChatPage = createReactContainer(
  "AgentDraftChatPage",
  useAgentDraftChatContainer,
  AgentDraftChat,
);
