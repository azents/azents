import { useTranslations } from "next-intl";

export function useAgentFormTranslations(): ReturnType<
  typeof useTranslations<"workspace.agents">
> {
  return useTranslations("workspace.agents");
}

export type AgentFormTranslator = ReturnType<typeof useAgentFormTranslations>;
