"use client";

import { rem } from "@mantine/core";
import { WorkspaceSettingsLayout } from "@/features/workspace-settings/components/WorkspaceSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeProfiles } from "./components/RuntimeProfiles";
import { useRuntimeProfilesContainer } from "./containers/useRuntimeProfilesContainer";
import type { RuntimeProfilesContainerOutput } from "./containers/useRuntimeProfilesContainer";
import type { WorkspaceResponse } from "@azents/public-client";

interface RuntimeProfilesPageProps {
  handle: string;
  workspace: WorkspaceResponse;
}

interface ConnectedRuntimeProfilesProps
  extends RuntimeProfilesContainerOutput, RuntimeProfilesPageProps {}

function useConnectedRuntimeProfilesContainer(
  props: RuntimeProfilesPageProps,
): ConnectedRuntimeProfilesProps {
  return {
    ...props,
    ...useRuntimeProfilesContainer({ handle: props.handle }),
  };
}

function ConnectedRuntimeProfiles(
  props: ConnectedRuntimeProfilesProps,
): React.ReactElement {
  return (
    <WorkspaceSettingsLayout
      workspace={props.workspace}
      backTarget="settings"
      backMaxWidth={rem(1080)}
    >
      <RuntimeProfiles {...props} />
    </WorkspaceSettingsLayout>
  );
}

export const RuntimeProfilesPage = createReactContainer(
  "RuntimeProfilesPage",
  useConnectedRuntimeProfilesContainer,
  ConnectedRuntimeProfiles,
);
