"use client";

import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  CopyButton,
  Group,
  Paper,
  rem,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import type { KimiOAuthDeviceState } from "../types";

const KIMI_AUTH_URL = "https://auth.kimi.com";

export type KimiOAuthConnectionStatus =
  | "connected"
  | "refresh_required"
  | "temporarily_unavailable"
  | "disabled";

export interface KimiOAuthConnectionCardProps {
  canManage: boolean;
  connectionStatus: KimiOAuthConnectionStatus | null;
  reconnect: boolean;
  state: KimiOAuthDeviceState;
  starting: boolean;
  cancelling: boolean;
  onStart: () => void;
  onCancel: () => void;
}

export function KimiOAuthConnectionCard({
  canManage,
  connectionStatus,
  reconnect,
  state,
  starting,
  cancelling,
  onStart,
  onCancel,
}: KimiOAuthConnectionCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.kimiOAuth");
  const format = useFormatter();

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap="xs">
          <Group gap="xs">
            <Title order={4}>{t("title")}</Title>
            <Badge color="violet" variant="light">
              {t("experimentalBadge")}
            </Badge>
          </Group>
          <Text c="dimmed" size="sm">
            {t("description")}
          </Text>
          <Text c="dimmed" size="xs">
            {t("deviceOnly")}
          </Text>
          <Text c="dimmed" size="xs">
            {t("availabilityNotice")}
          </Text>
        </Stack>
        <KimiConnectionStatusBadge
          status={state.type === "CONNECTED" ? "connected" : connectionStatus}
        />
      </Group>

      {state.type === "ERROR" ? (
        <Alert color="red" title={t("connectionFailed")}>
          {state.message}
        </Alert>
      ) : null}

      {state.type === "PENDING" ? (
        <Alert color="blue" aria-live="polite">
          <Stack gap="xs">
            <Text>
              {t.rich("deviceInstruction", {
                link: (chunks) => (
                  <Anchor
                    href={state.verificationUri || KIMI_AUTH_URL}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {chunks}
                  </Anchor>
                ),
              })}
            </Text>
            <Button
              component="a"
              href={state.verificationUri || KIMI_AUTH_URL}
              target="_blank"
              rel="noreferrer"
              rightSection={<IconExternalLink size={rem(16)} />}
              fullWidth
            >
              {t("openVerificationPage")}
            </Button>
            <Paper withBorder p="xs" radius="sm">
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text ff="monospace" truncate>
                  {state.userCode}
                </Text>
                <CopyButton value={state.userCode}>
                  {({ copied, copy }) => (
                    <Tooltip
                      label={copied ? t("copied") : t("copyCode")}
                      withArrow
                    >
                      <ActionIcon
                        aria-label={copied ? t("copied") : t("copyCode")}
                        variant="subtle"
                        color={copied ? "teal" : "gray"}
                        onClick={copy}
                      >
                        {copied ? (
                          <IconCheck size={rem(16)} />
                        ) : (
                          <IconCopy size={rem(16)} />
                        )}
                      </ActionIcon>
                    </Tooltip>
                  )}
                </CopyButton>
              </Group>
            </Paper>
            <Text c="dimmed" size="xs">
              {t("expiresAt", {
                value: format.dateTime(new Date(state.expiresAt), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </Text>
          </Stack>
        </Alert>
      ) : null}

      {canManage ? (
        <Group gap="sm">
          <Button
            onClick={onStart}
            loading={starting}
            disabled={state.type === "PENDING"}
          >
            {state.type === "ERROR"
              ? t("tryAgain")
              : reconnect
                ? t("reconnectWithDeviceCode")
                : t("connectWithDeviceCode")}
          </Button>
          {state.type === "PENDING" ? (
            <Button
              variant="subtle"
              color="red"
              onClick={onCancel}
              loading={cancelling}
            >
              {t("cancel")}
            </Button>
          ) : null}
        </Group>
      ) : null}
    </Stack>
  );
}

export function KimiConnectionStatusBadge({
  status,
}: {
  status: KimiOAuthConnectionStatus | null;
}): React.ReactElement | null {
  const t = useTranslations("workspace.llmSettings.kimiOAuth");
  switch (status) {
    case "connected":
      return (
        <Badge color="green" variant="light">
          {t("connected")}
        </Badge>
      );
    case "refresh_required":
      return (
        <Badge color="orange" variant="light">
          {t("reconnectRequired")}
        </Badge>
      );
    case "temporarily_unavailable":
      return (
        <Badge color="yellow" variant="light">
          {t("temporarilyUnavailable")}
        </Badge>
      );
    case "disabled":
      return (
        <Badge color="gray" variant="outline">
          {t("disabled")}
        </Badge>
      );
    case null:
      return null;
  }
}
