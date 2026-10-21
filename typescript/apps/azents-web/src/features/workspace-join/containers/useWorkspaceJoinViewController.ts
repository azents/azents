"use client";

import { useState } from "react";
import type { WorkspaceJoinViewProps } from "./useWorkspaceJoinContainer";

export interface WorkspaceJoinViewOutput extends WorkspaceJoinViewProps {
  message: string;
  setMessage: (message: string) => void;
  submitMessage: () => void;
}
export function useWorkspaceJoinViewController(
  props: WorkspaceJoinViewProps,
): WorkspaceJoinViewOutput {
  const [message, setMessage] = useState("");
  return {
    ...props,
    message,
    setMessage,
    submitMessage: () =>
      props.onSubmitRequest(message.trim() ? message.trim() : null),
  };
}
