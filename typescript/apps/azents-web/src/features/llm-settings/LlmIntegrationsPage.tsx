"use client";

/** Focused LLM integrations settings page entry. */

import { rem } from "@mantine/core";
import { WorkspaceSettingsLayout } from "@/features/workspace-settings/components/WorkspaceSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LlmIntegrations } from "./components/LlmIntegrations";
import { SubscriptionUsageContainer } from "./containers/SubscriptionUsageContainer";
import { useLlmIntegrationsContainer } from "./containers/useLlmIntegrationsContainer";
import type { LlmIntegrationsContainerOutput } from "./containers/useLlmIntegrationsContainer";
import type { WorkspaceResponse } from "@azents/public-client";

interface LlmIntegrationsPageProps {
  handle: string;
  workspace: WorkspaceResponse;
}

interface ConnectedLlmIntegrationsProps
  extends LlmIntegrationsContainerOutput, LlmIntegrationsPageProps {}

function useConnectedLlmIntegrationsContainer(
  props: LlmIntegrationsPageProps,
): ConnectedLlmIntegrationsProps {
  return {
    ...props,
    ...useLlmIntegrationsContainer({ handle: props.handle }),
  };
}

function ConnectedLlmIntegrations(
  props: ConnectedLlmIntegrationsProps,
): React.ReactElement {
  return (
    <WorkspaceSettingsLayout
      workspace={props.workspace}
      backTarget="settings"
      backMaxWidth={rem(860)}
    >
      <LlmIntegrations
        {...props}
        renderSubscriptionUsage={(integration) => (
          <SubscriptionUsageContainer
            enabled={integration.enabled}
            handle={props.handle}
            integrationId={integration.id}
            provider={integration.provider}
          />
        )}
      />
    </WorkspaceSettingsLayout>
  );
}

export const LlmIntegrationsPage = createReactContainer(
  "LlmIntegrationsPage",
  useConnectedLlmIntegrationsContainer,
  ConnectedLlmIntegrations,
);
