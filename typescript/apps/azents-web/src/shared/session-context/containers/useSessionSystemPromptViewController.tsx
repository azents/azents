"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type {
  SessionContextResponse,
  SessionContextSystemPromptFragmentResponse,
  SessionContextSystemPromptResponse,
} from "@azents/public-client";
interface SessionSystemPromptViewProps {
  context: SessionContextResponse;
}
function promptDetailId(
  group: "agent" | "toolkit" | "injected" | "final",
  id: string,
): string {
  return `${group}:${id}`;
}
export interface SessionSystemPromptViewViewProps {
  t: ReturnType<typeof useTranslations<"chat.context">>;
  setSelectedPromptId: React.Dispatch<React.SetStateAction<string | null>>;
  systemPrompt: SessionContextSystemPromptResponse | null;
  agentPrompt: SessionContextSystemPromptFragmentResponse | null;
  finalPrompt: SessionContextSystemPromptFragmentResponse | null;
  promptDetails: {
    id: string;
    prompt: SessionContextSystemPromptFragmentResponse;
  }[];
  selectedPrompt: SessionContextSystemPromptFragmentResponse | null;
}
export function useSessionSystemPromptViewController({
  context,
}: SessionSystemPromptViewProps): SessionSystemPromptViewViewProps {
  const t = useTranslations("chat.context");
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);
  const systemPrompt = context.system_prompt ?? null;
  const agentPrompt = systemPrompt?.agent_prompt ?? null;
  const finalPrompt = systemPrompt?.final_prompt ?? null;
  const promptDetails = [
    ...(agentPrompt
      ? [
          {
            id: promptDetailId("agent", agentPrompt.id),
            prompt: agentPrompt,
          },
        ]
      : []),
    ...(systemPrompt?.toolkit_prompts.map((prompt) => ({
      id: promptDetailId("toolkit", prompt.id),
      prompt,
    })) ?? []),
    ...(systemPrompt?.injected_prompts.map((prompt) => ({
      id: promptDetailId("injected", prompt.id),
      prompt,
    })) ?? []),
    ...(finalPrompt
      ? [
          {
            id: promptDetailId("final", finalPrompt.id),
            prompt: finalPrompt,
          },
        ]
      : []),
  ];
  const selectedPrompt =
    promptDetails.find((detail) => detail.id === selectedPromptId)?.prompt ??
    null;
  return {
    t,
    setSelectedPromptId,
    systemPrompt,
    agentPrompt,
    finalPrompt,
    promptDetails,
    selectedPrompt,
  };
}
