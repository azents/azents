"use client";

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Checkbox,
  Divider,
  Group,
  Paper,
  Skeleton,
  Stack,
  Text,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { AgentWorkspaceEnvironmentSettings } from "@azents/public-client";

export interface AgentWorkspaceEnvironmentSelectionProps {
  handle: string;
  state:
    | { type: "LOADING" }
    | { type: "ERROR"; message: string }
    | {
        type: "READY";
        settings: AgentWorkspaceEnvironmentSettings;
        selectedIds: string[];
        dirty: boolean;
        saving: boolean;
        saved: boolean;
        error: string | null;
      };
  onToggle: (id: string, checked: boolean) => void;
  onSave: () => void;
  onDiscard: () => void;
  onRetry: () => void;
}

export function AgentWorkspaceEnvironmentSelection({
  handle,
  state,
  onToggle,
  onSave,
  onDiscard,
  onRetry,
}: AgentWorkspaceEnvironmentSelectionProps): React.ReactElement {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  return (
    <Paper
      withBorder
      radius="lg"
      p="lg"
      component="section"
      aria-label={t("selectionTitle")}
    >
      <Stack gap="md">
        <Group justify="space-between">
          <Text fw={700}>{t("selectionTitle")}</Text>
          <Badge color="gray" variant="light">
            {t("optIn")}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed">
          {t("selectionDescription")}
        </Text>
        {state.type === "LOADING" ? (
          <Skeleton height="4rem" />
        ) : state.type === "ERROR" ? (
          <Alert color="red">
            <Stack>
              <Text>{state.message}</Text>
              <Button variant="light" onClick={onRetry}>
                {t("retry")}
              </Button>
            </Stack>
          </Alert>
        ) : (
          <>
            {state.settings.entries.length === 0 ? (
              <Text size="sm" c="dimmed">
                {t("workspaceEmpty")}
              </Text>
            ) : (
              <Stack gap="sm">
                {state.settings.entries.map((entry) => (
                  <Checkbox
                    key={entry.id}
                    label={entry.name}
                    checked={state.selectedIds.includes(entry.id)}
                    disabled={!state.settings.can_manage || state.saving}
                    description={
                      state.settings.overridden_names.includes(entry.name)
                        ? t("agentOverride")
                        : null
                    }
                    onChange={(event) =>
                      onToggle(entry.id, event.currentTarget.checked)
                    }
                  />
                ))}
              </Stack>
            )}
            <Text size="xs" c="dimmed">
              {t("selectionNotice")}
            </Text>
            {state.error ? (
              <Alert color="red" role="alert">
                {state.error}
              </Alert>
            ) : null}
            <Divider />
            <Group justify="space-between">
              <Text
                size="sm"
                role="status"
                c={state.dirty ? "orange" : "dimmed"}
              >
                {state.dirty
                  ? t("unsaved")
                  : state.saved
                    ? t("saved")
                    : t("selectedCount", { count: state.selectedIds.length })}
              </Text>
              {state.settings.can_manage ? (
                <Group gap="xs">
                  <Button
                    variant="default"
                    disabled={!state.dirty || state.saving}
                    onClick={onDiscard}
                  >
                    {t("discard")}
                  </Button>
                  <Button
                    disabled={!state.dirty || state.saving}
                    loading={state.saving}
                    onClick={onSave}
                  >
                    {t("save")}
                  </Button>
                </Group>
              ) : (
                <Text size="xs" c="dimmed">
                  {t("readOnly")}
                </Text>
              )}
            </Group>
          </>
        )}
        <Anchor
          component={Link}
          href={`/w/${handle}/settings/environment`}
          size="sm"
        >
          {t("manageWorkspace")}
        </Anchor>
      </Stack>
    </Paper>
  );
}
