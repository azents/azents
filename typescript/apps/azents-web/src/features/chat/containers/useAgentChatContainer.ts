"use client";

/**
 * Agent detail Chat tab container.
 *
 * Agent is fixed from URL. The selected session is URL state and is validated
 * through the backend before mounting chat state.
 */

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { ConnectionStatus } from "@/features/chat/types";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

export interface AgentChatContainerProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session: AgentSessionResponse;
}

export type AgentChatSessionState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; session: AgentSessionResponse };

export interface AgentChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  sessionState: AgentChatSessionState;
  /** ChatSessionView mount identifier */
  mountKey: string;
  mountSessionId: string;
  sessionConnectionStatus: ConnectionStatus;
  onConnectionStatusChange: (status: ConnectionStatus) => void;
}

export function useAgentChatContainer(
  props: AgentChatContainerProps,
): AgentChatContainerOutput {
  const { handle, agent, sessionId, session } = props;
  const sessionQuery = trpc.chat.getAgentSession.useQuery(
    {
      agentId: agent.id,
      sessionId,
    },
    { initialData: session },
  );

  const sessionState: AgentChatSessionState = {
    type: "LOADED",
    session: sessionQuery.data,
  };

  const [sessionConnectionStatus, setSessionConnectionStatus] =
    useState<ConnectionStatus>("disconnected");

  const onConnectionStatusChange = useCallback(
    (status: ConnectionStatus): void => {
      setSessionConnectionStatus(status);
    },
    [],
  );

  const mountKey: string = useMemo(() => sessionId, [sessionId]);

  return {
    handle,
    agent,
    sessionId,
    sessionState,
    mountKey,
    mountSessionId: sessionId,
    sessionConnectionStatus,
    onConnectionStatusChange,
  };
}
