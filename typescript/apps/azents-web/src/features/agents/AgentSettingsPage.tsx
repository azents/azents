"use client";

/**
 * Agent settings page entry.
 */

import { Box } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentHeader } from "./components/AgentHeader";
import { AgentSettings } from "./components/AgentSettings";
import { useAgentSettingsContainer } from "./containers/useAgentSettingsContainer";
import type { AgentSettingsContainerOutput } from "./containers/useAgentSettingsContainer";

function AgentSettingsWithHeader(
  props: AgentSettingsContainerOutput,
): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentHeader handle={props.handle} agent={props.agent} />
      <AgentSettings {...props} />
    </Box>
  );
}

export const AgentSettingsPage = createReactContainer(
  "AgentSettingsPage",
  useAgentSettingsContainer,
  AgentSettingsWithHeader,
);
