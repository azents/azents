"use client";

/** Agent Runtime settings page entry. */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentRuntimeEnvironmentVariablesSection } from "./AgentRuntimeEnvironmentVariablesSection";
import { AgentRuntimeSettings } from "./components/AgentRuntimeSettings";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import { useAgentRuntimeSettingsContainer } from "./containers/useAgentRuntimeSettingsContainer";
import type { AgentRuntimeSettingsContainerOutput } from "./containers/useAgentRuntimeSettingsContainer";

function AgentRuntimeSettingsWithHeader(
  props: AgentRuntimeSettingsContainerOutput,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentRuntimeSettings
        {...props}
        environmentVariables={
          <AgentRuntimeEnvironmentVariablesSection
            handle={props.handle}
            agentId={props.agent.id}
          />
        }
      />
    </AgentSettingsLayout>
  );
}

export const AgentRuntimeSettingsPage = createReactContainer(
  "AgentRuntimeSettingsPage",
  useAgentRuntimeSettingsContainer,
  AgentRuntimeSettingsWithHeader,
);
