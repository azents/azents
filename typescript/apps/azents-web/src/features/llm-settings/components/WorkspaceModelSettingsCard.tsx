"use client";

/** Prop-driven Workspace default model settings card. */

import { Alert, Button, Card, Group, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import type { FormEventHandler, ReactNode } from "react";

export interface WorkspaceModelSettingsCardProps {
  modelOptionsEditor: ReactNode;
  canManage: boolean;
  submitting: boolean;
  error: string | null;
  onSubmit: FormEventHandler<HTMLFormElement>;
}

export function WorkspaceModelSettingsCard({
  modelOptionsEditor,
  canManage,
  submitting,
  error,
  onSubmit,
}: WorkspaceModelSettingsCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.modelSelection");

  return (
    <Card withBorder padding="md">
      <form onSubmit={onSubmit}>
        <Stack gap="md">
          <Stack gap="xs">
            <Text fw={600}>{t("title")}</Text>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Stack>
          {modelOptionsEditor}
          {error && <Alert color="red">{error}</Alert>}
          {canManage && (
            <Group justify="flex-end">
              <Button type="submit" loading={submitting}>
                {t("save")}
              </Button>
            </Group>
          )}
        </Stack>
      </form>
    </Card>
  );
}
