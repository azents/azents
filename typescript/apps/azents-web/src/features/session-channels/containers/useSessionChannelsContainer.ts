"use client";

import { useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { sessionChannelDisconnectInvalidationPlan } from "../invalidation";
import type { SessionChannelsState } from "../types";
import type { AgentResponse, ManagedBinding } from "@azents/public-client";

export interface SessionChannelsContainerProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
}

export interface SessionChannelsContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  state: SessionChannelsState;
  actionError: string | null;
  disconnectingId: string | null;
  onDisconnect: (binding: ManagedBinding) => void;
}

function normalizeError(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function useSessionChannelsContainer({
  handle,
  agent,
  sessionId,
}: SessionChannelsContainerProps): SessionChannelsContainerOutput {
  const utils = trpc.useUtils();
  const [actionError, setActionError] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const disconnectLock = useRef(false);
  const sessionInput = { agentId: agent.id, sessionId };
  const channelInput = { handle, ...sessionInput };
  const sessionQuery = trpc.chat.getAgentSession.useQuery(sessionInput);
  const channelsQuery =
    trpc.externalChannel.listSessionChannels.useQuery(channelInput);
  const disconnectMutation =
    trpc.externalChannel.disconnectSessionChannel.useMutation({
      onSuccess: async () => {
        try {
          await Promise.all(
            sessionChannelDisconnectInvalidationPlan().map((target) => {
              switch (target) {
                case "sessionChannels":
                  return utils.externalChannel.listSessionChannels.invalidate(
                    channelInput,
                  );
                case "connections":
                  return utils.externalChannel.listConnections.invalidate({
                    handle,
                    agentId: agent.id,
                  });
              }
            }),
          );
        } finally {
          disconnectLock.current = false;
          setActionError(null);
          setDisconnectingId(null);
        }
      },
      onError: (error) => {
        disconnectLock.current = false;
        setActionError(normalizeError(error));
        setDisconnectingId(null);
      },
    });

  const state: SessionChannelsState =
    sessionQuery.isPending || channelsQuery.isPending
      ? { type: "LOADING" }
      : sessionQuery.isError
        ? { type: "ERROR", message: sessionQuery.error.message }
        : channelsQuery.isError
          ? { type: "ERROR", message: channelsQuery.error.message }
          : {
              type: "LOADED",
              session: sessionQuery.data,
              bindings: channelsQuery.data.items,
              grants: channelsQuery.data.grants,
            };

  return {
    handle,
    agent,
    sessionId,
    state,
    actionError,
    disconnectingId,
    onDisconnect: (binding) => {
      if (disconnectLock.current) {
        return;
      }
      disconnectLock.current = true;
      setActionError(null);
      setDisconnectingId(binding.id);
      disconnectMutation.mutate({
        ...channelInput,
        bindingId: binding.id,
      });
    },
  };
}
