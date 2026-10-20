"use client";

/**
 * Agent detail Chat tab container.
 *
 * Agent is fixed from URL. The selected session is URL state and is validated
 * through the backend before mounting chat state.
 */

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
import type { ConnectionStatus } from "@azents/session-core/types";

export interface AgentChatContainerProps {
  renderSupportingContent: import("../session-panel/supportingPanel").SupportingPanelRenderer;
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
  renderSupportingContent: import("../session-panel/supportingPanel").SupportingPanelRenderer;
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

  const { handle, agent, sessionId, session } = props;
  const router = useRouter();
  const utils = trpc.useUtils();
  const agentQuery = trpc.agent.get.useQuery(
    { handle, agentId: agent.id },
    {
      initialData: agent,
      staleTime: 0,
      refetchOnMount: false,
      refetchOnWindowFocus: true,
      refetchInterval: (query) =>
        query.state.error?.data?.code === "NOT_FOUND"
          ? false
          : query.state.data?.deletion_status != null
            ? 5000
            : false,
      refetchIntervalInBackground: false,
    },
  );
  useEffect(() => {
    if (agentQuery.error?.data?.code === "NOT_FOUND") {
      router.replace(`/w/${encodeURIComponent(handle)}/agents`);
    }
  }, [agentQuery.error, handle, router]);
  const [hydratedAgent, setHydratedAgent] = useState<{
    agent: AgentResponse;
    handle: string;
  } | null>(null);
  useEffect(() => {
    let current = true;
    const input = { handle, agentId: agent.id };
    // Retire pre-boundary reads before seeding current server props or refreshing.
    void utils.agent.get.cancel(input).then(() => {
      if (!current) {
        return;
      }
      utils.agent.get.setData(input, (current) =>
        current?.deletion_status != null && agent.deletion_status === null
          ? { ...agent, deletion_status: current.deletion_status }
          : agent,
      );
      setHydratedAgent({ agent, handle });
      void utils.agent.get.invalidate(input);
    });
    return () => {
      current = false;
    };
  }, [agent, handle, utils.agent.get]);
  const currentAgent =
    hydratedAgent?.agent === agent && hydratedAgent.handle === handle
      ? agentQuery.data
      : agent;
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
    renderSupportingContent: props.renderSupportingContent,
    handle,
    agent: currentAgent,
    sessionId,
    sessionState,
    mountKey,
    mountSessionId: sessionId,
    sessionConnectionStatus,
    onConnectionStatusChange,
  };
}
