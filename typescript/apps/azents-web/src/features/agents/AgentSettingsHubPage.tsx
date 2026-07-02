"use client";

/** Agent settings hub page entry. */

import { Box } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSettingsHeader } from "./components/AgentSettingsHeader";
import { AgentSettingsHub } from "./components/AgentSettingsHub";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsHubContainerProps {
  handle: string;
  agent: AgentResponse;
}

function useAgentSettingsHubContainer(
  props: AgentSettingsHubContainerProps,
): AgentSettingsHubContainerProps {
  return props;
}

function AgentSettingsHubWithHeader({
  handle,
  agent,
}: AgentSettingsHubContainerProps): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSettingsHeader agent={agent} />
      <AgentSettingsHub handle={handle} agent={agent} />
    </Box>
  );
}

export const AgentSettingsHubPage = createReactContainer(
  "AgentSettingsHubPage",
  useAgentSettingsHubContainer,
  AgentSettingsHubWithHeader,
);
