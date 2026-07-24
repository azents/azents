"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentAutomaticProjects } from "./components/AgentAutomaticProjects";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import { useAgentAutomaticProjectsContainer } from "./containers/useAgentAutomaticProjectsContainer";
import type { AgentAutomaticProjectsContainerOutput } from "./containers/useAgentAutomaticProjectsContainer";

function AgentAutomaticProjectsWithHeader(
  props: AgentAutomaticProjectsContainerOutput,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentAutomaticProjects {...props} />
    </AgentSettingsLayout>
  );
}

export const AgentAutomaticProjectsPage = createReactContainer(
  "AgentAutomaticProjectsPage",
  useAgentAutomaticProjectsContainer,
  AgentAutomaticProjectsWithHeader,
);
