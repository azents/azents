import { LlmIntegrationsPage } from "./LlmIntegrationsPage";
import { WorkspaceModelSettingsPage } from "./WorkspaceModelSettingsPage";
import type { WorkspaceResponse } from "@azents/public-client";

interface WorkspaceSettingsSectionPageProps {
  section: "models" | "llm-integrations";
  handle: string;
  workspace: WorkspaceResponse;
}

export function WorkspaceSettingsSectionPage({
  section,
  handle,
  workspace,
}: WorkspaceSettingsSectionPageProps): React.ReactElement {
  return section === "models" ? (
    <WorkspaceModelSettingsPage handle={handle} workspace={workspace} />
  ) : (
    <LlmIntegrationsPage handle={handle} workspace={workspace} />
  );
}
