"use client";

import { useTranslations } from "next-intl";
import { AgentSettingsLayout } from "@/shared/agent-session/AgentSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentVaultSettings } from "./components/AgentVaultSettings";
import { useAgentVaultSettings } from "./containers/useAgentVaultSettings";
import type { AgentVaultSettingsProps } from "./components/AgentVaultSettings";
import type { AgentResponse } from "@azents/public-client";

interface PageProps {
  handle: string;
  agent: AgentResponse;
}

function usePage(props: PageProps): PageProps & AgentVaultSettingsProps {
  return { ...props, ...useAgentVaultSettings(props.handle, props.agent.id) };
}

function SettingsWithHeader(
  props: PageProps & AgentVaultSettingsProps,
): React.ReactElement {
  const t = useTranslations("workspace.agents.vault");
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentVaultSettings {...props} t={t} />
    </AgentSettingsLayout>
  );
}

export const AgentVaultSettingsPage = createReactContainer(
  "AgentVaultSettingsPage",
  usePage,
  SettingsWithHeader,
);
