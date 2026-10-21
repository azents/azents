"use client";
import { useCallback, useRef } from "react";
import { useAgentAvatarContainer } from "./useAgentAvatarContainer";
import type { AvatarUploadState } from "./useAgentAvatarContainer";
import type { AgentResponse } from "@azents/public-client";
interface AgentAvatarSectionProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentAvatarSectionViewProps {
  agent: AgentAvatarSectionProps["agent"];
  state: AvatarUploadState;
  removeAvatar: () => Promise<void>;
  inputRef: React.RefObject<HTMLInputElement | null>;
  handlePickFile: () => void;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  busy: boolean;
}
export function useAgentAvatarSectionController({
  handle,
  agent,
}: AgentAvatarSectionProps): AgentAvatarSectionViewProps {
  const { state, uploadFile, removeAvatar, reset } = useAgentAvatarContainer({
    handle,
    agentId: agent.id,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  const handlePickFile = useCallback(() => {
    reset();
    inputRef.current?.click();
  }, [reset]);

  const handleFileChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      event.target.value = "";
      if (!file) {
        return;
      }
      void uploadFile(file);
    },
    [uploadFile],
  );

  const busy =
    state.type === "validating" ||
    state.type === "requesting-url" ||
    state.type === "uploading" ||
    state.type === "finalizing" ||
    state.type === "removing";
  return {
    agent,
    state,
    removeAvatar,
    inputRef,
    handlePickFile,
    handleFileChange,
    busy,
  };
}
