"use client";

import { Anchor, Box, rem, Stack } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentRuntimeEnvironmentVariables } from "@/shared/runtime-environment/AgentRuntimeEnvironmentVariables";
import { useWorkspaceEnvironmentContainer } from "./containers/useWorkspaceEnvironmentContainer";
import type { RuntimeEnvironmentVariablesProps } from "@/shared/runtime-environment/types";

function WorkspaceEnvironmentView(
  props: RuntimeEnvironmentVariablesProps & { handle: string },
): React.ReactElement {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  return (
    <Box style={{ overflow: "auto", height: "100%" }}>
      <Stack p="md" maw={rem(960)} mx="auto">
        <Anchor component={Link} href={`/w/${props.handle}/settings`} size="sm">
          {t("backToWorkspaceSettings")}
        </Anchor>
        <AgentRuntimeEnvironmentVariables {...props} />
      </Stack>
    </Box>
  );
}

export const WorkspaceEnvironmentPage = createReactContainer(
  "WorkspaceEnvironmentPage",
  useWorkspaceEnvironmentContainer,
  WorkspaceEnvironmentView,
);
