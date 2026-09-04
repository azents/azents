"use client";

import { useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { sessionChannelDisconnectInvalidationPlan } from "../invalidation";
import { useAgentSessionTitleUpdater } from "./useAgentSessionTitleUpdater";
import type { SessionChannelsState } from "../types";
import type {
  AgentResponse,
  AgentSessionResponse,
  ExternalChannelResponseMode,
  ManagedBinding,
} from "@azents/public-client";

export interface SessionChannelsContainerProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session: AgentSessionResponse;
}

export interface SessionChannelsContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session: AgentSessionResponse;
  onUpdateTitle: (title: string | null) => Promise<AgentSessionResponse>;
  state: SessionChannelsState;
  actionError: string | null;
  disconnectingId: string | null;
  responseModeDrafts: Record<string, ExternalChannelResponseMode>;
  updatingResponseModeId: string | null;
  responseModeError: { bindingId: string; message: string } | null;
  onDisconnect: (binding: ManagedBinding) => void;
  onResponseModeChange: (
    binding: ManagedBinding,
    responseMode: ExternalChannelResponseMode,
  ) => void;
  onSaveResponseMode: (binding: ManagedBinding) => void;
}

function normalizeError(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

export function useSessionChannelsContainer({
  handle,
  agent,
  sessionId,
  session,
}: SessionChannelsContainerProps): SessionChannelsContainerOutput {
  const utils = trpc.useUtils();
  const onUpdateTitle = useAgentSessionTitleUpdater(agent.id, sessionId);
  const [actionError, setActionError] = useState<string | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const [responseModeDrafts, setResponseModeDrafts] = useState<
    Record<string, ExternalChannelResponseMode>
  >({});
  const [updatingResponseModeId, setUpdatingResponseModeId] = useState<
    string | null
  >(null);
  const [responseModeError, setResponseModeError] = useState<{
    bindingId: string;
    message: string;
  } | null>(null);
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
  const responseModeMutation =
    trpc.externalChannel.updateBindingResponseMode.useMutation({
      onSuccess: async (binding) => {
        try {
          await utils.externalChannel.listSessionChannels.invalidate(
            channelInput,
          );
          setResponseModeDrafts((drafts) => {
            const next = { ...drafts };
            delete next[binding.id];
            return next;
          });
          setResponseModeError(null);
        } catch (error) {
          setResponseModeError({
            bindingId: binding.id,
            message: normalizeError(error),
          });
        } finally {
          setUpdatingResponseModeId(null);
        }
      },
      onError: (error, variables) => {
        setResponseModeError({
          bindingId: variables.bindingId,
          message: normalizeError(error),
        });
        setUpdatingResponseModeId(null);
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
    session,
    onUpdateTitle,
    state,
    actionError,
    disconnectingId,
    responseModeDrafts,
    updatingResponseModeId,
    responseModeError,
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
    onResponseModeChange: (binding, responseMode) => {
      setResponseModeDrafts((drafts) => ({
        ...drafts,
        [binding.id]: responseMode,
      }));
      setResponseModeError(null);
    },
    onSaveResponseMode: (binding) => {
      const responseMode =
        responseModeDrafts[binding.id] ?? binding.response_mode;
      if (
        responseMode === binding.response_mode ||
        updatingResponseModeId !== null ||
        binding.disconnected_at !== null
      ) {
        return;
      }
      setResponseModeError(null);
      setUpdatingResponseModeId(binding.id);
      responseModeMutation.mutate({
        ...channelInput,
        bindingId: binding.id,
        responseMode,
      });
    },
  };
}
