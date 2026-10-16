"use client";

/**
 * Agent detail Chat tab UI.
 *
 * Renders one URL-selected Agent session across full area, centered on Direct chat.
 * WebSocket/buffer is isolated by per-session remount (ChatSessionView key).
 */

import { Box, Center, Loader, Text } from "@mantine/core";
import { ChatSessionViewContainer } from "@/features/chat/containers/useChatSessionViewContainer";
import styles from "./AgentChatTab.module.css";
import type { AgentChatContainerOutput } from "../containers/useAgentChatContainer";

export function AgentChatTab(
  props: AgentChatContainerOutput,
): React.ReactElement {
  const {
    agent,
    sessionState,
    mountKey,
    mountSessionId,
    onConnectionStatusChange,
  } = props;

  switch (sessionState.type) {
    case "LOADING": {
      return (
        <Center className={styles.chatArea} style={{ flex: 1, minHeight: 0 }}>
          <Loader size="lg" />
        </Center>
      );
    }

    case "ERROR": {
      return (
        <Center className={styles.chatArea} style={{ flex: 1, minHeight: 0 }}>
          <Text c="red">{sessionState.message}</Text>
        </Center>
      );
    }

    case "LOADED": {
      break;
    }
  }

  return (
    <Box className={styles.chatArea} style={{ flex: 1, minHeight: 0 }}>
      <ChatSessionViewContainer
        renderSupportingContent={props.renderSupportingContent}
        key={mountKey}
        handle={props.handle}
        sessionId={mountSessionId}
        agent={agent}
        session={sessionState.session}
        onConnectionStatusChange={onConnectionStatusChange}
      />
    </Box>
  );
}
