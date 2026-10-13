"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Paper,
  PasswordInput,
  rem,
  Skeleton,
  Stack,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import classes from "./AgentRuntimeEnvironmentVariables.module.css";
import type { RuntimeEnvironmentVariablesProps } from "../runtime-environment-types";

/** Agent-scoped secret editor; values and mutations are supplied by its container. */
export function AgentRuntimeEnvironmentVariables({
  state,
  onAdd,
  onNameChange,
  onValueChange,
  onRemove,
  onDiscard,
  onSave,
  onRetry,
}: RuntimeEnvironmentVariablesProps): React.ReactElement {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  const ready = state.type === "READY" ? state : null;
  const saving = ready?.status.type === "SAVING";
  const editable = ready?.canManage === true && !saving;
  const dirty =
    ready?.status.type === "DIRTY" || ready?.status.type === "ERROR";
  const invalid = ready?.entries.some(
    (entry) => entry.nameError || entry.valueError,
  );

  return (
    <Paper
      withBorder
      radius="lg"
      p="lg"
      component="section"
      aria-label={t("title")}
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" gap="sm">
          <Stack gap={4}>
            <Text fw={700}>{t("title")}</Text>
            <Text c="dimmed" size="sm">
              {t("description")}
            </Text>
          </Stack>
          <Badge variant="light" color="gray">
            {t("scope")}
          </Badge>
        </Group>

        {state.type === "LOADING" ? (
          <Stack aria-label={t("loading")}>
            <Skeleton height={rem(36)} />
            <Skeleton height={rem(36)} />
          </Stack>
        ) : null}

        {state.type === "ERROR" ? (
          <Alert color="red" title={t("loadError")}>
            <Stack gap="sm">
              <Text size="sm">{state.message}</Text>
              <Button
                variant="light"
                color="red"
                onClick={onRetry}
                w="fit-content"
              >
                {t("retry")}
              </Button>
            </Stack>
          </Alert>
        ) : null}

        {ready ? (
          <>
            {ready.entries.length === 0 ? (
              <Stack gap={4} py="sm">
                <Text size="sm" fw={500}>
                  {t("emptyTitle")}
                </Text>
                <Text size="sm" c="dimmed">
                  {t("emptyDescription")}
                </Text>
              </Stack>
            ) : (
              <Stack gap="md">
                {ready.entries.map((entry) => (
                  <div className={classes.row} key={entry.id}>
                    <TextInput
                      className={classes.name}
                      classNames={{ input: classes.nameInput }}
                      label={t("name")}
                      aria-label={t("nameFor", {
                        name: entry.name || t("newVariable"),
                      })}
                      placeholder="API_TOKEN"
                      autoComplete="off"
                      spellCheck={false}
                      maxLength={64}
                      value={entry.name}
                      error={entry.nameError}
                      disabled={!editable}
                      onChange={(event) =>
                        onNameChange(entry.id, event.currentTarget.value)
                      }
                    />
                    <PasswordInput
                      className={classes.value}
                      label={t("value")}
                      aria-label={t("valueFor", {
                        name: entry.name || t("newVariable"),
                      })}
                      placeholder={
                        entry.hasStoredValue
                          ? t("storedPlaceholder")
                          : t("newPlaceholder")
                      }
                      description={
                        entry.hasStoredValue ? t("keepStored") : null
                      }
                      inputWrapperOrder={[
                        "label",
                        "input",
                        "description",
                        "error",
                      ]}
                      autoComplete="new-password"
                      maxLength={4096}
                      value={entry.value}
                      error={entry.valueError}
                      disabled={!editable}
                      visibilityToggleButtonProps={{
                        "aria-label": t("toggleValue"),
                      }}
                      onChange={(event) =>
                        onValueChange(entry.id, event.currentTarget.value)
                      }
                    />
                    {ready.canManage ? (
                      <Tooltip
                        label={t("remove", {
                          name: entry.name || t("newVariable"),
                        })}
                      >
                        <ActionIcon
                          className={classes.remove}
                          variant="subtle"
                          color="red"
                          size="lg"
                          disabled={saving}
                          aria-label={t("remove", {
                            name: entry.name || t("newVariable"),
                          })}
                          onClick={() => onRemove(entry.id)}
                        >
                          <IconTrash size={rem(18)} />
                        </ActionIcon>
                      </Tooltip>
                    ) : null}
                  </div>
                ))}
              </Stack>
            )}
            {ready.canManage ? (
              <Button
                variant="subtle"
                leftSection={<IconPlus size={rem(16)} />}
                onClick={onAdd}
                disabled={saving || ready.entries.length >= 50}
                w="fit-content"
                px="xs"
              >
                {t("add")}
              </Button>
            ) : null}
            <Text size="xs" c="dimmed">
              {t("protectionNotice")}
            </Text>
            {ready.status.type === "ERROR" ? (
              <Alert color="red" role="alert">
                {ready.status.message}
              </Alert>
            ) : null}
            <Divider />
            <Group justify="space-between" align="center" gap="sm">
              <Text
                size="sm"
                c={
                  dirty
                    ? "orange"
                    : ready.status.type === "SAVED"
                      ? "green"
                      : "dimmed"
                }
                role="status"
                aria-live="polite"
              >
                {!ready.canManage
                  ? t("readOnly")
                  : dirty
                    ? t("unsaved")
                    : ready.status.type === "SAVING"
                      ? t("saving")
                      : ready.status.type === "SAVED"
                        ? t("saved")
                        : t("count", { count: ready.entries.length })}
              </Text>
              {ready.canManage ? (
                <Group gap="xs">
                  <Button
                    variant="default"
                    onClick={onDiscard}
                    disabled={!dirty || saving}
                  >
                    {t("discard")}
                  </Button>
                  <Button
                    onClick={onSave}
                    disabled={!dirty || invalid || saving}
                    loading={saving}
                  >
                    {t("save")}
                  </Button>
                </Group>
              ) : null}
            </Group>
          </>
        ) : null}
      </Stack>
    </Paper>
  );
}
