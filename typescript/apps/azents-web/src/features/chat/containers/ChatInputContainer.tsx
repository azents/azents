"use client";

import { memo } from "react";
import { ChatInput } from "../components/ChatInput";
import { useChatInputContainer } from "./useChatInputContainer";
import type { ChatInputProps } from "./useChatInputContainer";

export const ChatInputContainer = memo(function ChatInputContainer(
  props: ChatInputProps,
): React.ReactElement {
  return <ChatInput view={useChatInputContainer(props)} />;
});
