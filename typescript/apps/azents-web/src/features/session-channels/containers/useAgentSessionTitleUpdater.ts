"use client";

import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { AgentSessionResponse } from "@azents/public-client";

export function useAgentSessionTitleUpdater(
  agentId: string,
  sessionId: string,
): (title: string | null) => Promise<AgentSessionResponse> {
  const utils = trpc.useUtils();
  const mutation = trpc.chat.updateAgentSessionTitle.useMutation();

  return useCallback(
    async (title: string | null): Promise<AgentSessionResponse> => {
      const updatedSession = await mutation.mutateAsync({
        agentId,
        sessionId,
        title,
      });
      await Promise.all([
        utils.chat.getAgentSession.invalidate({ agentId, sessionId }),
        utils.chat.listAgentSessions.invalidate({ agentId }),
        utils.chat.listAgentUserSessions.invalidate({ agentId }),
        utils.chat.getAgentSessionSidebar.invalidate({ agentId }),
      ]);
      return updatedSession;
    },
    [
      agentId,
      mutation,
      sessionId,
      utils.chat.getAgentSession,
      utils.chat.getAgentSessionSidebar,
      utils.chat.listAgentSessions,
      utils.chat.listAgentUserSessions,
    ],
  );
}
