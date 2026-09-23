"use client";

/** xAI OAuth connection card. */

import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  CopyButton,
  Group,
  Paper,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconCheck, IconCopy, IconExternalLink } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

const DEVICE_VERIFICATION_URL = "https://accounts.x.ai";

export type XaiOAuthDeviceState =
  | { type: "IDLE" }
  | {
      type: "PENDING";
      sessionId: string;
      userCode: string;
      verificationUri: string;
      intervalMs: number;
    }
  | { type: "CONNECTED" }
  | { type: "ERROR"; message: string };

interface XaiOAuthConnectionCardProps {
  canManage: boolean;
  integrationId?: string;
  state: XaiOAuthDeviceState;
  starting: boolean;
  cancelling: boolean;
  onStart: () => void;
  onCancel: () => void;
}

export function XaiOAuthConnectionCard({
  canManage,
  integrationId,
  state,
  starting,
  cancelling,
  onStart,
  onCancel,
}: XaiOAuthConnectionCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.xaiOAuth");
  const isBusy = starting || cancelling;
  const pendingDescription =
    state.type === "PENDING"
      ? t.rich("deviceInstruction", {
          link: (chunks) => (
            <Anchor
              href={state.verificationUri || DEVICE_VERIFICATION_URL}
              target="_blank"
              rel="noreferrer"
            >
              {chunks}
            </Anchor>
          ),
        })
      : null;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap="xs">
          <Group gap="xs">
            <Title order={4}>{t("title")}</Title>
            <Badge color="teal" variant="light">
              {t("oauthBadge")}
            </Badge>
          </Group>
          <Text c="dimmed" size="sm">
            {t("description")}
          </Text>
          <Text c="dimmed" size="xs">
            {t("callbackUnavailable")}
          </Text>
        </Stack>
        {state.type === "CONNECTED" && (
          <Badge color="green" variant="light">
            {t("connected")}
          </Badge>
        )}
      </Group>

      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}

      {state.type === "PENDING" && (
        <Alert color="blue">
          <Stack gap="xs">
            <Text>{pendingDescription}</Text>
            <Button
              component="a"
              href={state.verificationUri || DEVICE_VERIFICATION_URL}
              target="_blank"
              rel="noreferrer"
              rightSection={<IconExternalLink size={16} />}
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
                          <IconCheck size={16} />
                        ) : (
                          <IconCopy size={16} />
                        )}
                      </ActionIcon>
                    </Tooltip>
                  )}
                </CopyButton>
              </Group>
            </Paper>
          </Stack>
        </Alert>
      )}

      {canManage && (
        <Group gap="sm">
          <Button
            onClick={onStart}
            loading={starting}
            disabled={state.type === "PENDING"}
          >
            {integrationId
              ? t("reauthenticateWithDeviceCode")
              : t("connectWithDeviceCode")}
          </Button>
          {state.type === "PENDING" && (
            <Button
              variant="subtle"
              color="red"
              onClick={onCancel}
              loading={isBusy}
            >
              {t("cancel")}
            </Button>
          )}
        </Group>
      )}
    </Stack>
  );
}
