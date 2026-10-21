"use client";

/** Workspace settings overview page. */

import { rem } from "@mantine/core";
import { WorkspaceSettingsLayout } from "../../shared/workspace-settings/WorkspaceSettingsLayout";
import { WorkspaceSettingsHub } from "./components/WorkspaceSettingsHub";
import type { WorkspaceResponse } from "@azents/public-client";

interface WorkspaceSettingsHubPageProps {
  workspace: WorkspaceResponse;
}

export function WorkspaceSettingsHubPage({
  workspace,
}: WorkspaceSettingsHubPageProps): React.ReactElement {
  return (
    <WorkspaceSettingsLayout
      workspace={workspace}
      backTarget="workspace"
      backMaxWidth={rem(860)}
    >
      <WorkspaceSettingsHub handle={workspace.handle} />
    </WorkspaceSettingsLayout>
  );
}
