import { useTranslations } from "next-intl";

export function useAgentFormTranslations() {
  return useTranslations("workspace.agents");
}

export type AgentFormTranslator = ReturnType<typeof useAgentFormTranslations>;
