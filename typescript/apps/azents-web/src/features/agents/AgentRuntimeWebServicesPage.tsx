"use client";

import { Box, rem } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeWebServices } from "@/shared/runtime-web/components/RuntimeWebServices";
import { AgentSettingsLayout } from "../../shared/agent-session/AgentSettingsLayout";
import { useAgentRuntimeWebServicesContainer } from "./containers/useAgentRuntimeWebServicesContainer";
import type { AgentRuntimeWebServicesContainerOutput } from "./containers/useAgentRuntimeWebServicesContainer";

function AgentRuntimeWebServicesWithHeader({
  handle,
  agent,
  runtimeWebServices,
}: AgentRuntimeWebServicesContainerOutput): React.ReactElement {
  return (
    <AgentSettingsLayout handle={handle} agent={agent} backTarget="settings">
      <Box p="md" maw={rem(960)} mx="auto" w="100%">
        <RuntimeWebServices {...runtimeWebServices} />
      </Box>
    </AgentSettingsLayout>
  );
}

export const AgentRuntimeWebServicesPage = createReactContainer(
  "AgentRuntimeWebServicesPage",
  useAgentRuntimeWebServicesContainer,
  AgentRuntimeWebServicesWithHeader,
);
