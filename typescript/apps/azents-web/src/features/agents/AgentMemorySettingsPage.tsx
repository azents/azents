"use client";

/** Agent Memory settings page entry. */

import { Box } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentMemorySettings } from "./components/AgentMemorySettings";
import { AgentSettingsHeader } from "./components/AgentSettingsHeader";
import { useAgentMemorySettingsContainer } from "./containers/useAgentMemorySettingsContainer";
import type { AgentMemorySettingsContainerOutput } from "./containers/useAgentMemorySettingsContainer";

function AgentMemorySettingsWithHeader(
  props: AgentMemorySettingsContainerOutput,
): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSettingsHeader agent={props.agent} />
      <AgentMemorySettings {...props} />
    </Box>
  );
}

export const AgentMemorySettingsPage = createReactContainer(
  "AgentMemorySettingsPage",
  useAgentMemorySettingsContainer,
  AgentMemorySettingsWithHeader,
);
