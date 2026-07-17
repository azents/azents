import {
  Box,
  Button,
  Group,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import { IconAlertTriangle, IconClock, IconRefresh } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import inlineControlClasses from "./ChatInlineControl.module.css";
import type {
  AgentRunPhase,
  ChatLiveRunRecovery,
  ChatLiveRunRetryState,
} from "../types";

type RunRetryCardProps =
  | {
      variant: "live";
      retry: ChatLiveRunRetryState;
      phase: AgentRunPhase;
    }
  | {
      variant: "stopped";
      recoveryKind: ChatLiveRunRecovery["kind"];
      message: string;
      canRetry: boolean;
      isRetryPending: boolean;
      onRetry: () => void;
    }
  | {
      variant: "terminal";
      message: string;
      canRetry: boolean;
      isRetryPending: boolean;
      onRetry: () => void;
    };

function timestampMs(iso: string): number | null {
  const value = new Date(iso).getTime();
  return Number.isFinite(value) ? value : null;
}

function useRetryCountdown(nextRetryAt: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (nextRetryAt === null) {
      return;
    }
    const target = timestampMs(nextRetryAt);
    if (target === null || target <= Date.now()) {
      setNow(Date.now());
      return;
    }
    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [nextRetryAt]);

  if (nextRetryAt === null) {
    return null;
  }
  const target = timestampMs(nextRetryAt);
  if (target === null) {
    return null;
  }
  return Math.max(0, Math.ceil((target - now) / 1000));
}

const MODEL_PROVIDER_ERROR_PREFIX = "Model provider error:";

function isProviderMessage(message: string): boolean {
  return message.startsWith(MODEL_PROVIDER_ERROR_PREFIX);
}

function providerMessageBody(message: string): string {
  return isProviderMessage(message)
    ? message.slice(MODEL_PROVIDER_ERROR_PREFIX.length).trim()
    : message;
}

export function RunRetryCard(props: RunRetryCardProps): React.ReactElement {
  const t = useTranslations("chat");
  const isLive = props.variant === "live";
  const rawMessage = isLive ? props.retry.lastErrorMessage : props.message;
  const countdown = useRetryCountdown(isLive ? props.retry.nextRetryAt : null);
  const genericStopped =
    props.variant === "stopped" && props.recoveryKind === "stopped";
  const providerFailure =
    props.variant === "stopped"
      ? props.recoveryKind === "provider_failure"
      : isProviderMessage(rawMessage);
  const title = genericStopped
    ? t("failedRunRecovery.stoppedTitle")
    : providerFailure
      ? t("failedRunRecovery.providerErrorTitle")
      : t("failedRunRecovery.errorTitle");
  const message = providerMessageBody(rawMessage);

  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Paper
        withBorder
        radius="lg"
        p="sm"
        bg="var(--mantine-color-body)"
        style={{ maxWidth: rem(680), overflow: "hidden" }}
      >
        <Stack gap="sm">
          <Group gap="xs" align="flex-start" wrap="nowrap">
            <IconAlertTriangle
              aria-hidden="true"
              size={rem(20)}
              stroke={1.8}
              color="var(--mantine-color-orange-6)"
              style={{ flexShrink: 0 }}
            />
            <Text size="sm" fw={700}>
              {title}
            </Text>
          </Group>

          {message !== "" && !genericStopped && (
            <Paper
              withBorder
              radius="md"
              p="xs"
              bg="var(--mantine-color-default-hover)"
            >
              <ScrollArea.Autosize mah={rem(110)} type="auto" scrollbars="y">
                <Text
                  size="sm"
                  lh={rem(22)}
                  style={{ overflowWrap: "anywhere" }}
                >
                  {message}
                </Text>
              </ScrollArea.Autosize>
            </Paper>
          )}

          {isLive && countdown !== null && (
            <Group
              gap={rem(6)}
              c="dimmed"
              wrap="nowrap"
              className={inlineControlClasses.root}
            >
              <IconClock aria-hidden="true" size={rem(14)} stroke={1.8} />
              <Text size="xs" className={inlineControlClasses.label}>
                {countdown > 0
                  ? t("failedRunRecovery.nextRetryCountdown", {
                      seconds: countdown,
                    })
                  : t("failedRunRecovery.retryingNow")}
              </Text>
            </Group>
          )}

          {!isLive && props.canRetry && (
            <Group gap="xs" justify="flex-end" wrap="wrap">
              <Button
                size="xs"
                variant="light"
                color="orange"
                leftSection={<IconRefresh size={rem(14)} />}
                loading={props.isRetryPending}
                onClick={props.onRetry}
              >
                {t("failedRunRecovery.retryAction")}
              </Button>
            </Group>
          )}
        </Stack>
      </Paper>
    </Box>
  );
}
