import {
  Badge,
  Box,
  Button,
  Collapse,
  Group,
  Paper,
  rem,
  ScrollArea,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconChevronRight,
  IconClock,
  IconRefresh,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { useMemo } from "react";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import {
  useAttemptHistory,
  useRunRetryCard,
} from "../containers/useRunRetryCard";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import type { RunRetryCardProps } from "../containers/useRunRetryCard";
import type { FailedRunAttemptSummary } from "@azents/session-core/types";

const MODEL_PROVIDER_ERROR_PREFIX = "Model provider error:";

function providerMessageBody(message: string): string {
  return message.startsWith(MODEL_PROVIDER_ERROR_PREFIX)
    ? message.slice(MODEL_PROVIDER_ERROR_PREFIX.length).trim()
    : message;
}

function formatFullDateTime(iso: string, locale: string): string {
  const date = new Date(iso);
  if (!Number.isFinite(date.getTime())) {
    return iso;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function AttemptHistoryView({
  attempts,
  opened,
  toggle,
}: {
  attempts: FailedRunAttemptSummary[];
  opened: boolean;
  toggle: () => void;
}): React.ReactElement | null {
  const t = useTranslations("chat");
  const locale = useLocale();
  const sortedAttempts = useMemo(
    () => [...attempts].sort((a, b) => b.attemptNumber - a.attemptNumber),
    [attempts],
  );

  if (sortedAttempts.length === 0) {
    return null;
  }

  return (
    <Stack gap={rem(6)}>
      <Group
        gap={rem(6)}
        wrap="nowrap"
        role="button"
        tabIndex={0}
        className={inlineControlClasses.root}
        style={{ cursor: "pointer", userSelect: "none" }}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        }}
      >
        <IconChevronRight
          aria-hidden="true"
          size={14}
          stroke={1.8}
          color="var(--mantine-color-dimmed)"
          style={{
            transform: opened ? "rotate(90deg)" : "none",
            transition: chatChevronTransition,
          }}
        />
        <Text
          size="xs"
          fw={600}
          c="dimmed"
          className={inlineControlClasses.label}
        >
          {t("failedRunRecovery.history", { count: sortedAttempts.length })}
        </Text>
      </Group>
      <Collapse
        expanded={opened}
        keepMounted={false}
        {...chatCollapseTransitionProps}
      >
        <ScrollArea.Autosize mah={rem(280)} scrollbars="y">
          <Stack gap="xs">
            {sortedAttempts.map((attempt) => (
              <Paper
                key={`${attempt.attemptNumber}:${attempt.failedAt}`}
                withBorder
                radius="md"
                p="xs"
                bg="var(--mantine-color-body)"
              >
                <Stack gap={rem(4)}>
                  <Group gap="xs" justify="space-between" wrap="nowrap">
                    <Text size="xs" fw={600}>
                      {t("failedRunRecovery.attemptTitle", {
                        attemptNumber: attempt.attemptNumber,
                      })}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {formatFullDateTime(attempt.failedAt, locale)}
                    </Text>
                  </Group>
                  <Text size="xs" style={{ overflowWrap: "anywhere" }}>
                    {attempt.userMessage}
                  </Text>
                  <Group gap="xs" wrap="wrap">
                    <Badge size="xs" variant="light" color="gray">
                      {attempt.errorType}
                    </Badge>
                  </Group>
                </Stack>
              </Paper>
            ))}
          </Stack>
        </ScrollArea.Autosize>
      </Collapse>
    </Stack>
  );
}

const AttemptHistory = createReactContainer(
  "AttemptHistory",
  useAttemptHistory,
  AttemptHistoryView,
);

export function RunRetryCardView({
  props,
  countdown,
}: {
  props: RunRetryCardProps;
  countdown: number | null;
}): React.ReactElement {
  const t = useTranslations("chat");
  const isLive = props.variant === "live";
  const providerFailure = isLive
    ? props.retry.errorKind === "model_provider"
    : props.failure.error_kind === "model_provider";
  const attempts = providerFailure
    ? []
    : isLive
      ? props.retry.attempts
      : (props.failure.attempts ?? []);
  const rawMessage = isLive ? props.retry.lastErrorMessage : props.message;
  const message = providerFailure
    ? providerMessageBody(rawMessage)
    : rawMessage;

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
              {providerFailure
                ? t("failedRunRecovery.providerErrorTitle")
                : t("failedRunRecovery.errorTitle")}
            </Text>
          </Group>

          {message && (
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
              <IconClock aria-hidden="true" size={14} stroke={1.8} />
              <Text size="xs" className={inlineControlClasses.label}>
                {countdown > 0
                  ? t("failedRunRecovery.nextRetryCountdown", {
                      seconds: countdown,
                    })
                  : t("failedRunRecovery.retryingNow")}
              </Text>
            </Group>
          )}

          <AttemptHistory attempts={attempts} />

          {!isLive && props.canRetry && (
            <Group gap="xs" justify="flex-end" wrap="wrap">
              <Button
                size="xs"
                variant="light"
                color="orange"
                leftSection={<IconRefresh size={14} />}
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

export const RunRetryCard = createReactContainer(
  "RunRetryCard",
  useRunRetryCard,
  RunRetryCardView,
);
