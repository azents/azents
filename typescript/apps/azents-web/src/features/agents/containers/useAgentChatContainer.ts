"use client";

/**
 * Agent detail Chat tab container.
 *
 * Agent is fixed from URL. Active session is fetched from backend active AgentSession
 * and stored only in internal state, not exposed in URL.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type { ConnectionStatus } from "@/features/chat/types";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

export interface AgentChatContainerProps {
  handle: string;
  agent: AgentResponse;
}

export type AgentChatActiveSessionState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; session: AgentSessionResponse };

export interface AgentChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  activeSessionId: string | null;
  activeSessionState: AgentChatActiveSessionState;
  /** ChatSessionView mount identifier */
  mountKey: string;
  mountInitialSessionId: string | null;
  sessionConnectionStatus: ConnectionStatus;
  onConnectionStatusChange: (status: ConnectionStatus) => void;
  onInnerSessionCreated: (sessionId: string) => void;
}

export function useAgentChatContainer(
  props: AgentChatContainerProps,
): AgentChatContainerOutput {
  const { handle, agent } = props;
  const activeSessionQuery = trpc.chat.getActiveAgentSession.useQuery({
    agentId: agent.id,
  });

  const activeSessionState: AgentChatActiveSessionState =
    activeSessionQuery.isPending
      ? { type: "LOADING" }
      : activeSessionQuery.isError
        ? { type: "ERROR", message: activeSessionQuery.error.message }
        : { type: "LOADED", session: activeSessionQuery.data };

  const [mountNonce, setMountNonce] = useState(0);
  const [mountSessionId, setMountSessionId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const prevActiveSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    const nextSessionId = activeSessionQuery.data?.id ?? null;
    if (
      nextSessionId !== null &&
      prevActiveSessionIdRef.current !== nextSessionId
    ) {
      prevActiveSessionIdRef.current = nextSessionId;
      setActiveSessionId(nextSessionId);
      setMountSessionId(nextSessionId);
      setMountNonce((n) => n + 1);
    }
  }, [activeSessionQuery.data?.id]);

  const [sessionConnectionStatus, setSessionConnectionStatus] =
    useState<ConnectionStatus>("disconnected");

  const onInnerSessionCreated = useCallback((sessionId: string) => {
    setActiveSessionId(sessionId);
    if (prevActiveSessionIdRef.current !== sessionId) {
      prevActiveSessionIdRef.current = sessionId;
      setMountSessionId(sessionId);
      setMountNonce((n) => n + 1);
    }
  }, []);

  const onConnectionStatusChange = useCallback((status: ConnectionStatus) => {
    setSessionConnectionStatus(status);
  }, []);

  const effectiveMountSessionId =
    mountSessionId ?? activeSessionQuery.data?.id ?? null;
  const effectiveActiveSessionId =
    activeSessionId ?? activeSessionQuery.data?.id ?? null;

  const mountKey: string = useMemo(() => {
    if (effectiveMountSessionId) {
      return effectiveMountSessionId;
    }
    return `new:${agent.id}:${mountNonce}`;
  }, [effectiveMountSessionId, agent.id, mountNonce]);

  return {
    handle,
    agent,
    activeSessionId: effectiveActiveSessionId,
    activeSessionState,
    mountKey,
    mountInitialSessionId: effectiveMountSessionId,
    sessionConnectionStatus,
    onConnectionStatusChange,
    onInnerSessionCreated,
  };
}
