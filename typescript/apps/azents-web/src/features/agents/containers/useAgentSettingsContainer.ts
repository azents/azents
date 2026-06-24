"use client";

/**
 * Agent Settings tab container.
 *
 * Wraps useAgentFormContainer for embedded mode — after successful save,
 * overrides afterSavePath to stay on settings page.
 */

import { useAgentFormContainer } from "./useAgentFormContainer";
import type { AgentFormContainerOutput } from "./useAgentFormContainer";
import type { AgentResponse } from "@azents/public-client";

export interface AgentSettingsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export type AgentSettingsContainerOutput = AgentFormContainerOutput & {
  handle: string;
  agent: AgentResponse;
};

export function useAgentSettingsContainer(
  props: AgentSettingsContainerProps,
): AgentSettingsContainerOutput {
  const { handle, agent } = props;
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
  };
}
