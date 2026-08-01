"use client";

/** Focused Workspace model settings page entry. */

import { WorkspaceSettingsLayout } from "@/features/workspace-settings/components/WorkspaceSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceModelSettings } from "./components/WorkspaceModelSettings";
import { useWorkspaceModelSettingsContainer } from "./containers/useWorkspaceModelSettingsContainer";
import type { WorkspaceModelSettingsContainerOutput } from "./containers/useWorkspaceModelSettingsContainer";
import type { WorkspaceResponse } from "@azents/public-client";

interface WorkspaceModelSettingsPageProps {
  handle: string;
  workspace: WorkspaceResponse;
}

interface ConnectedWorkspaceModelSettingsProps
  extends
    WorkspaceModelSettingsContainerOutput,
    WorkspaceModelSettingsPageProps {}

function useConnectedWorkspaceModelSettingsContainer(
  props: WorkspaceModelSettingsPageProps,
): ConnectedWorkspaceModelSettingsProps {
  return {
    ...props,
    ...useWorkspaceModelSettingsContainer({ handle: props.handle }),
  };
}

function ConnectedWorkspaceModelSettings(
  props: ConnectedWorkspaceModelSettingsProps,
): React.ReactElement {
  return (
    <WorkspaceSettingsLayout workspace={props.workspace} backTarget="settings">
      <WorkspaceModelSettings {...props} />
    </WorkspaceSettingsLayout>
  );
}

export const WorkspaceModelSettingsPage = createReactContainer(
  "WorkspaceModelSettingsPage",
  useConnectedWorkspaceModelSettingsContainer,
  ConnectedWorkspaceModelSettings,
);
