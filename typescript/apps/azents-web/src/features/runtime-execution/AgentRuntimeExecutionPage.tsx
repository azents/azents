"use client";

import { AgentSettingsLayout } from "@/features/agents/components/AgentSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentRuntimeExecution } from "./components/AgentRuntimeExecution";
import { useAgentRuntimeExecutionContainer } from "./containers/useAgentRuntimeExecutionContainer";
import type { AgentRuntimeExecutionProps } from "./types";

function AgentRuntimeExecutionWithLayout(
  props: AgentRuntimeExecutionProps,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentRuntimeExecution {...props} />
    </AgentSettingsLayout>
  );
}

export const AgentRuntimeExecutionPage = createReactContainer(
  "AgentRuntimeExecutionPage",
  useAgentRuntimeExecutionContainer,
  AgentRuntimeExecutionWithLayout,
);
