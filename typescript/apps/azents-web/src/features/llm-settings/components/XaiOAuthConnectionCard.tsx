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
import { IconCheck, IconCopy } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";

const DEVICE_VERIFICATION_URL = "https://accounts.x.ai";

type DeviceState =
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
  handle: string;
  canManage: boolean;
  onConnected?: () => void;
}

export function XaiOAuthConnectionCard({
  handle,
  canManage,
  onConnected,
}: XaiOAuthConnectionCardProps): React.ReactElement {
  const t = useTranslations("workspace.llmSettings.xaiOAuth");
  const utils = trpc.useUtils();
  const [deviceState, setDeviceState] = useState<DeviceState>({ type: "IDLE" });

  const deviceStartMutation =
    trpc.llmProviderIntegration.startXaiOauthDevice.useMutation({
      onSuccess: (data) => {
        setDeviceState({
          type: "PENDING",
          sessionId: data.session_id,
          userCode: data.user_code,
          verificationUri: data.verification_uri,
          intervalMs: data.interval_seconds * 1000,
        });
      },
      onError: (error) => {
        setDeviceState({ type: "ERROR", message: error.message });
      },
    });

  const cancelMutation =
    trpc.llmProviderIntegration.cancelXaiOauthDevice.useMutation({
      onSuccess: () => {
        setDeviceState({ type: "IDLE" });
      },
    });

  const deviceSessionId =
    deviceState.type === "PENDING" ? deviceState.sessionId : "";
  const deviceStatusQuery =
    trpc.llmProviderIntegration.getXaiOauthDeviceStatus.useQuery(
      { handle, sessionId: deviceSessionId },
      {
        enabled: deviceState.type === "PENDING",
        refetchInterval:
          deviceState.type === "PENDING" ? deviceState.intervalMs : false,
      },
    );

  useEffect(() => {
    if (deviceStatusQuery.data?.status === "connected") {
      setDeviceState({ type: "CONNECTED" });
      void utils.llmProviderIntegration.list.invalidate({ handle });
      onConnected?.();
    } else if (
      deviceStatusQuery.data?.status === "expired" ||
      deviceStatusQuery.data?.status === "failed" ||
      deviceStatusQuery.data?.status === "cancelled"
    ) {
      setDeviceState({
        type: "ERROR",
        message: t("statusError", { status: deviceStatusQuery.data.status }),
      });
    }
  }, [deviceStatusQuery.data?.status, handle, onConnected, t, utils]);

  useEffect(() => {
    if (deviceStatusQuery.isError) {
      setDeviceState({
        type: "ERROR",
        message: deviceStatusQuery.error.message,
      });
    }
  }, [deviceStatusQuery.error?.message, deviceStatusQuery.isError]);

  const isBusy = deviceStartMutation.isPending || cancelMutation.isPending;

  const pendingDescription = useMemo((): React.ReactNode | null => {
    if (deviceState.type !== "PENDING") {
      return null;
    }
    const href = deviceState.verificationUri || DEVICE_VERIFICATION_URL;
    return t.rich("deviceInstruction", {
      link: (chunks) => (
        <Anchor href={href} target="_blank" rel="noreferrer">
          {chunks}
        </Anchor>
      ),
    });
  }, [deviceState, t]);

  const startDevice = useCallback((): void => {
    deviceStartMutation.mutate({ handle });
  }, [deviceStartMutation, handle]);

  const cancelDevice = useCallback((): void => {
    if (deviceState.type !== "PENDING") {
      return;
    }
    cancelMutation.mutate({ handle, sessionId: deviceState.sessionId });
  }, [cancelMutation, deviceState, handle]);

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
        {deviceState.type === "CONNECTED" && (
          <Badge color="green" variant="light">
            {t("connected")}
          </Badge>
        )}
      </Group>

      {deviceState.type === "ERROR" && (
        <Alert color="red">{deviceState.message}</Alert>
      )}

      {deviceState.type === "PENDING" && (
        <Alert color="blue">
          <Stack gap="xs">
            <Text>{pendingDescription}</Text>
            <Paper withBorder p="xs" radius="sm">
              <Group justify="space-between" wrap="nowrap" gap="xs">
                <Text ff="monospace" truncate>
                  {deviceState.userCode}
                </Text>
                <CopyButton value={deviceState.userCode}>
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
            onClick={startDevice}
            loading={deviceStartMutation.isPending}
            disabled={deviceState.type === "PENDING"}
          >
            {t("connectWithDeviceCode")}
          </Button>
          {deviceState.type === "PENDING" && (
            <Button
              variant="subtle"
              color="red"
              onClick={cancelDevice}
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
