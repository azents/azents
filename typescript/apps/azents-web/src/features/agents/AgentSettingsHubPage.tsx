"use client";

/** Agent settings hub page entry. */

import { rem } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { trpc } from "@/trpc/client";
import { AgentSettingsHub } from "./components/AgentSettingsHub";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsHubContainerProps {
  handle: string;
  agent: AgentResponse;
}

interface AgentSettingsHubContainerOutput extends AgentSettingsHubContainerProps {
  automaticProjectsCount: number | null;
}

function useAgentSettingsHubContainer(
  props: AgentSettingsHubContainerProps,
): AgentSettingsHubContainerOutput {
  const policyQuery = trpc.agent.getAutomaticSessionProjects.useQuery({
    handle: props.handle,
    agentId: props.agent.id,
  });
  return {
    ...props,
    automaticProjectsCount:
      policyQuery.data && policyQuery.data.project_paths.length > 0
        ? policyQuery.data.project_paths.length
        : null,
  };
}

function AgentSettingsHubWithHeader({
  handle,
  agent,
  automaticProjectsCount,
}: AgentSettingsHubContainerOutput): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={handle}
      agent={agent}
      backTarget="agent"
      backMaxWidth={rem(860)}
    >
      <AgentSettingsHub
        handle={handle}
        agent={agent}
        automaticProjectsCount={automaticProjectsCount}
      />
    </AgentSettingsLayout>
  );
}

export const AgentSettingsHubPage = createReactContainer(
  "AgentSettingsHubPage",
  useAgentSettingsHubContainer,
  AgentSettingsHubWithHeader,
);
