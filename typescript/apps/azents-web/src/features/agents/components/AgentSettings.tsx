"use client";

/**
 * Agent settings UI.
 *
 * First implementation: render existing `AgentForm` in embedded mode + Danger section at bottom.
 * Design 7-section subnav will be refined in follow-up PR.
 */

import { Divider, rem, Stack } from "@mantine/core";
import { AgentAvatarSection } from "./AgentAvatarSection";
import { AgentDangerSection } from "./AgentDangerSection";
import { AgentForm } from "./AgentForm";
import type { MemberItem } from "../containers/useAgentFormContainer";
import type {
  ModelCatalogState,
  ModelSelectionOption,
  ProviderIntegrationOption,
} from "../model-selection";
import type { AgentFormValues } from "../schemas";
import type { AdminListState, AgentFormState, MutationState } from "../types";
import type {
  AgentAdminResponse,
  AgentResponse,
  WorkspaceModelSettingsResponse,
} from "@azents/public-client";

type AgentSettingsSection =
  | "all"
  | "profile"
  | "model"
  | "capabilities"
  | "subagents"
  | "admins";

interface AgentSettingsProps {
  handle: string;
  agent: AgentResponse;
  section: AgentSettingsSection | "danger";
  formState: AgentFormState;
  mutationState: MutationState;
  adminListState: AdminListState;
  providerOptions: ProviderIntegrationOption[];
  modelOptions: ModelSelectionOption[];
  workspaceModelSettings: WorkspaceModelSettingsResponse | null;
  catalogStates: ReadonlyMap<string, ModelCatalogState>;
  modelsLoading: boolean;
  members: MemberItem[];
  onSyncCatalog: (integrationId: string) => void;
  onSubmit: (values: AgentFormValues) => void;
  onAddAdmin: (workspaceUserId: string) => void;
  onRemoveAdmin: (admin: AgentAdminResponse) => void;
}

export function AgentSettings(props: AgentSettingsProps): React.ReactElement {
  const { handle, agent, section, ...formProps } = props;
  const settingsHref = `/w/${handle}/agents/${agent.id}/settings`;

  if (section === "danger") {
    return (
      <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
        <Stack gap="xl" p="md" maw={rem(860)} mx="auto" w="100%">
          <div style={{ padding: "0 var(--mantine-spacing-lg)" }}>
            <AgentDangerSection handle={handle} agentId={agent.id} />
          </div>
        </Stack>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <Stack gap="xl" p="md" maw={rem(960)} mx="auto" w="100%">
        {section === "profile" && (
          <>
            <div style={{ padding: "0 var(--mantine-spacing-lg)" }}>
              <AgentAvatarSection handle={handle} agent={agent} />
            </div>
            <Divider />
          </>
        )}
        <AgentForm
          handle={handle}
          mode="embedded"
          section={section}
          cancelHref={settingsHref}
          {...formProps}
        />
      </Stack>
    </div>
  );
}
