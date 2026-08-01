"use client";

/** Focused Workspace default model settings UI. */

import { Alert, Box, Loader, rem, Stack, Text, Title } from "@mantine/core";
import { useTranslations } from "next-intl";
import { WorkspaceModelSettingsCard } from "./WorkspaceModelSettingsCard";
import type { WorkspaceModelSettingsContainerOutput } from "../containers/useWorkspaceModelSettingsContainer";

export function WorkspaceModelSettings(
  props: WorkspaceModelSettingsContainerOutput,
): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");

  return (
    <Box style={{ height: "100%", overflow: "auto", minHeight: 0 }}>
      <Stack gap="lg" p="md" maw={rem(960)} mx="auto" w="100%">
        <Stack gap={4}>
          <Title order={3}>{t("modelSelection.pageTitle")}</Title>
          <Text c="dimmed" size="sm">
            {t("modelSelection.pageDescription")}
          </Text>
        </Stack>
        {props.state.type === "LOADING" && <Loader />}
        {props.state.type === "ERROR" && (
          <Alert color="red">{t("modelSelection.loadError")}</Alert>
        )}
        {props.state.type === "READY" && (
          <WorkspaceModelSettingsCard
            settings={props.state.settings}
            handle={props.handle}
            providerOptions={props.providerOptions}
            canManage={props.canManage}
            submitting={props.mutationState.type === "SUBMITTING"}
            error={
              props.mutationState.type === "IDLE"
                ? props.mutationState.error
                : null
            }
            onSyncCatalog={props.onSyncCatalog}
            onSubmit={props.onSubmit}
          />
        )}
      </Stack>
    </Box>
  );
}
