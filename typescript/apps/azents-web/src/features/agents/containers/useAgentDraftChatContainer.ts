"use client";

/**
 * Agent draft chat container.
 *
 * Owns the pre-session first-message write and canonical URL replacement.
 */

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type { UploadedFile } from "@/features/chat/hooks/useFileUpload";
import type { AgentResponse } from "@azents/public-client";

export interface AgentDraftChatContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentDraftChatContainerOutput {
  handle: string;
  agent: AgentResponse;
  isWritePending: boolean;
  onSendMessage: (
    message: string,
    attachments?: UploadedFile[],
  ) => Promise<boolean>;
}

export function useAgentDraftChatContainer(
  props: AgentDraftChatContainerProps,
): AgentDraftChatContainerOutput {
  const { handle, agent } = props;
  const router = useRouter();
  const utils = trpc.useUtils();
  const createMessageMutation =
    trpc.chat.createTeamAgentSessionMessage.useMutation();
  const [writeInFlight, setWriteInFlight] = useState(false);

  const onSendMessage = useCallback(
    async (message: string, attachments?: UploadedFile[]): Promise<boolean> => {
      if (writeInFlight) {
        return false;
      }
      const attachmentUris = attachments?.map((attachment) => attachment.uri);
      setWriteInFlight(true);
      try {
        const response = await createMessageMutation.mutateAsync({
          agentId: agent.id,
          clientRequestId: crypto.randomUUID(),
          message,
          attachments: attachmentUris,
        });
        await utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
        router.replace(
          `/w/${handle}/agents/${agent.id}/sessions/${response.session_id}`,
        );
        return true;
      } catch {
        return false;
      } finally {
        setWriteInFlight(false);
      }
    },
    [
      agent.id,
      createMessageMutation,
      handle,
      router,
      utils.chat.listAgentSessions,
      writeInFlight,
    ],
  );

  return {
    handle,
    agent,
    isWritePending: createMessageMutation.isPending || writeInFlight,
    onSendMessage,
  };
}
