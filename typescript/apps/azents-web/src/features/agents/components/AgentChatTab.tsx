"use client";

/**
 * Agent detail Chat tab UI.
 *
 * Renders one URL-selected Agent session across full area, centered on Direct chat.
 * WebSocket/buffer is isolated by per-session remount (ChatSessionView key).
 */

import { Box, Center, Loader, Text } from "@mantine/core";
import { useEffect } from "react";
import { ChatSessionView } from "@/features/chat/components/ChatSessionView";
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

  // Lock outer document scroll on chat page.
  // Lock root too because locking only body can leave html scroll on iOS Safari.
  useEffect(() => {
    const root = document.documentElement;
    const body = document.body;
    const previousRootOverflow = root.style.overflow;
    const previousRootOverscrollBehavior = root.style.overscrollBehavior;
    const previousBodyOverflow = body.style.overflow;
    const previousBodyOverscrollBehavior = body.style.overscrollBehavior;

    root.style.overflow = "hidden";
    root.style.overscrollBehavior = "none";
    body.style.overflow = "hidden";
    body.style.overscrollBehavior = "none";

    return () => {
      root.style.overflow = previousRootOverflow;
      root.style.overscrollBehavior = previousRootOverscrollBehavior;
      body.style.overflow = previousBodyOverflow;
      body.style.overscrollBehavior = previousBodyOverscrollBehavior;
    };
  }, []);

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
      <ChatSessionView
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
