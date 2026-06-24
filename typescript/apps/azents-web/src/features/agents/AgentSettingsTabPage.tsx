"use client";

/**
 * Agent Settings tab entry.
 */

import { Box } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentHeader } from "./components/AgentHeader";
import { AgentSettingsTab } from "./components/AgentSettingsTab";
import { useAgentSettingsContainer } from "./containers/useAgentSettingsContainer";
import type { AgentSettingsContainerOutput } from "./containers/useAgentSettingsContainer";

function AgentSettingsTabWithHeader(
  props: AgentSettingsContainerOutput,
): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentHeader handle={props.handle} agent={props.agent} />
      <AgentSettingsTab {...props} />
    </Box>
  );
}

export const AgentSettingsTabPage = createReactContainer(
  "AgentSettingsTabPage",
  useAgentSettingsContainer,
  AgentSettingsTabWithHeader,
);
