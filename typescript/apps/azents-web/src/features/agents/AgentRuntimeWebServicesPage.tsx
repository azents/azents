"use client";

import { RuntimeWebServices } from "@/features/runtime-web/components/RuntimeWebServices";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import { useAgentRuntimeWebServicesContainer } from "./containers/useAgentRuntimeWebServicesContainer";
import type { AgentRuntimeWebServicesContainerOutput } from "./containers/useAgentRuntimeWebServicesContainer";

function AgentRuntimeWebServicesWithHeader({
  handle,
  agent,
  runtimeWebServices,
}: AgentRuntimeWebServicesContainerOutput): React.ReactElement {
  return (
    <AgentSettingsLayout handle={handle} agent={agent} backTarget="settings">
      <RuntimeWebServices {...runtimeWebServices} />
    </AgentSettingsLayout>
  );
}

export const AgentRuntimeWebServicesPage = createReactContainer(
  "AgentRuntimeWebServicesPage",
  useAgentRuntimeWebServicesContainer,
  AgentRuntimeWebServicesWithHeader,
);
