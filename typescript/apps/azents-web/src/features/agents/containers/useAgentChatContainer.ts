"use client";

/**
 * Agent detail Chat tab container.
 *
 * Agent is fixed from URL. The chat view starts without a selected session and
 * stores the created session id locally after the first message.
 */

import { useCallback, useMemo, useState } from "react";
import type { ConnectionStatus } from "@/features/chat/types";
import type { AgentResponse } from "@azents/public-client";

export interface AgentChatContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string | null;
  /** ChatSessionView mount identifier */
  mountKey: string;
  mountInitialSessionId: string | null;
  sessionConnectionStatus: ConnectionStatus;
  onConnectionStatusChange: (status: ConnectionStatus) => void;
  onSessionCreated: (sessionId: string) => void;
}

export function useAgentChatContainer(
  props: AgentChatContainerProps,
): AgentChatContainerOutput {
  const { handle, agent } = props;
  const [mountNonce, setMountNonce] = useState(0);
  const [mountSessionId, setMountSessionId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionConnectionStatus, setSessionConnectionStatus] =
    useState<ConnectionStatus>("disconnected");

  const onSessionCreated = useCallback((createdSessionId: string) => {
    setSessionId(createdSessionId);
    setMountSessionId(createdSessionId);
    setMountNonce((n) => n + 1);
  }, []);

  const onConnectionStatusChange = useCallback((status: ConnectionStatus) => {
    setSessionConnectionStatus(status);
  }, []);

  const mountKey: string = useMemo(() => {
    if (mountSessionId) {
      return mountSessionId;
    }
    return `new:${agent.id}:${mountNonce}`;
  }, [mountSessionId, agent.id, mountNonce]);

  return {
    handle,
    agent,
    sessionId,
    mountKey,
    mountInitialSessionId: mountSessionId,
    sessionConnectionStatus,
    onConnectionStatusChange,
    onSessionCreated,
  };
}
