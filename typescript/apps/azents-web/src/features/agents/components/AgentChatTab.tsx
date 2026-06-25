"use client";

/**
 * Agent detail Chat tab UI.
 *
 * Renders the Agent chat surface. The view may start without a session id; the
 * first message creates a concrete AgentSession.
 */

import { Box } from "@mantine/core";
import { useEffect } from "react";
import { ChatSessionView } from "@/features/chat/components/ChatSessionView";
import styles from "./AgentChatTab.module.css";
import type { AgentChatContainerOutput } from "../containers/useAgentChatContainer";

export function AgentChatTab(
  props: AgentChatContainerOutput,
): React.ReactElement {
  const {
    agent,
    mountKey,
    mountInitialSessionId,
    onConnectionStatusChange,
    onSessionCreated,
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

  return (
    <Box className={styles.chatArea} style={{ flex: 1, minHeight: 0 }}>
      <ChatSessionView
        key={mountKey}
        handle={props.handle}
        initialSessionId={mountInitialSessionId}
        agent={agent}
        onSessionCreated={onSessionCreated}
        onConnectionStatusChange={onConnectionStatusChange}
      />
    </Box>
  );
}
