"use client";
import { useTranslations } from "next-intl";
import { type ReactNode } from "react";
import { useAgentFocusedShellMobileNav } from "@/shared/agent-session/AgentFocusedShellMobileNav";
import { agentPrimaryModelSelection } from "@/shared/agent-session/modelSelection";
import { formatModelSelectionSummary } from "@/shared/agent-session/modelSelectionSummary";
import type { AgentFocusedShellMobileNav } from "@/shared/agent-session/AgentFocusedShellMobileNav";
import type { AgentResponse } from "@azents/public-client";
interface AgentSettingsHeaderProps {
  agent: AgentResponse;
  controls?: ReactNode;
}

export interface AgentSettingsHeaderViewProps {
  agent: AgentSettingsHeaderProps["agent"];
  controls: AgentSettingsHeaderProps["controls"];
  t: ReturnType<typeof useTranslations<"workspace.agents.detail">>;
  mobileNav: AgentFocusedShellMobileNav | null;
  modelSummary: string;
}
export function useAgentSettingsHeaderController({
  agent,
  controls,
}: AgentSettingsHeaderProps): AgentSettingsHeaderViewProps {
  const t = useTranslations("workspace.agents.detail");
  const mobileNav = useAgentFocusedShellMobileNav();
  const modelSummary = formatModelSelectionSummary(
    agentPrimaryModelSelection(agent),
  );
  return { agent, controls, t, mobileNav, modelSummary };
}
