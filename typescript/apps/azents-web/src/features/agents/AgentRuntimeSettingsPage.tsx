"use client";

/** Agent Runtime settings page entry. */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSettingsLayout } from "../../shared/agent-session/AgentSettingsLayout";
import { AgentBrowserChoiceSection } from "./AgentBrowserChoiceSection";
import { AgentRuntimeEnvironmentVariablesSection } from "./AgentRuntimeEnvironmentVariablesSection";
import { AgentWorkspaceEnvironmentSection } from "./AgentWorkspaceEnvironmentSection";
import { AgentRuntimeSettings } from "./components/AgentRuntimeSettings";
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
        browserConfiguration={
          <AgentBrowserChoiceSection
            handle={props.handle}
            agentId={props.agent.id}
            disabled={
              props.state.type !== "READY" ||
              props.state.runtime.capability === "removing"
            }
          />
        }
        environmentVariables={
          <>
            <AgentRuntimeEnvironmentVariablesSection
              handle={props.handle}
              agentId={props.agent.id}
            />
            <AgentWorkspaceEnvironmentSection
              handle={props.handle}
              agentId={props.agent.id}
            />
          </>
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
