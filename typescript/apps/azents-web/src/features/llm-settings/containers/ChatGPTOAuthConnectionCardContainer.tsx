"use client";

import { ChatGPTOAuthConnectionCard } from "../components/ChatGPTOAuthConnectionCard";
import { useChatGPTOAuthConnectionContainer } from "./useChatGPTOAuthConnectionContainer";

interface ChatGPTOAuthConnectionCardContainerProps {
  handle: string;
  canManage: boolean;
  integrationId?: string;
  onConnected?: () => void;
}

export function ChatGPTOAuthConnectionCardContainer({
  handle,
  canManage,
  integrationId,
  onConnected,
}: ChatGPTOAuthConnectionCardContainerProps): React.ReactElement {
  const container = useChatGPTOAuthConnectionContainer({
    handle,
    integrationId,
    onConnected,
  });
  return (
    <ChatGPTOAuthConnectionCard
      canManage={canManage}
      integrationId={integrationId}
      {...container}
    />
  );
}
