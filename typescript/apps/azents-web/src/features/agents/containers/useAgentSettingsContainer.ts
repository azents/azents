"use client";

/**
 * Agent Settings tab container.
 *
 * Wraps useAgentFormContainer for embedded mode — after successful save,
 * overrides afterSavePath to stay on settings page.
 */

import { useAgentFormContainer } from "./useAgentFormContainer";
import type { AgentFormSection } from "../components/AgentForm";
import type { AgentFormContainerOutput } from "./useAgentFormContainer";
import type { AgentResponse } from "@azents/public-client";

export interface AgentSettingsContainerProps {
  handle: string;
  agent: AgentResponse;
  section: AgentFormSection | "danger";
}

export type AgentSettingsContainerOutput = AgentFormContainerOutput & {
  handle: string;
  agent: AgentResponse;
  section: AgentFormSection | "danger";
};

export function useAgentSettingsContainer(
  props: AgentSettingsContainerProps,
): AgentSettingsContainerOutput {
  const { handle, agent, section } = props;
  const basePath = `/w/${handle}/agents/${agent.id}/settings`;

  const formOutput = useAgentFormContainer({
    handle,
    agentId: agent.id,
    afterSavePath: basePath,
  });

  return {
    ...formOutput,
    handle,
    agent,
    section,
  };
}
