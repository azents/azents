"use client";

import {
  Alert,
  Badge,
  Button,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconLock, IconWorld } from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import type { RuntimeWebConfirmationContainerOutput } from "../containers/useRuntimeWebConfirmationContainer";

function formatDuration(seconds: number, locale: string): string {
  const minutes = Math.round(seconds / 60);
  return new Intl.NumberFormat(locale).format(minutes);
}

export function RuntimeWebConfirmation({
  state,
  onApprove,
  onReject,
  onCancel,
  onClose,
  onRetry,
}: RuntimeWebConfirmationContainerOutput): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const locale = useLocale();
  if (state.type === "LOADING") {
    return (
      <Container size="xs" py="xl">
        <Group justify="center">
          <Loader size="sm" />
          <Text size="sm">{t("confirmation.loading")}</Text>
        </Group>
      </Container>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Container size="xs" py="xl">
        <Alert color="red" title={t("confirmation.errorTitle")}>
          <Stack gap="sm">
            <Text size="sm">{state.message}</Text>
            <Button variant="light" onClick={onRetry}>
              {t("retry")}
            </Button>
          </Stack>
        </Alert>
      </Container>
    );
  }

  const { service } = state;
  const request = service.current_request;
  const pending = request?.state === "pending";
  const duration = formatDuration(service.duration_seconds, locale);
  const label =
    request?.label ??
    service.endpoint.label ??
    t("service.portLabel", {
      port: service.endpoint.port,
    });

  return (
    <Container size="sm" py={{ base: "lg", sm: "xl" }}>
      <Paper withBorder radius="lg" p={{ base: "md", sm: "xl" }}>
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start">
            <Group gap="sm" wrap="nowrap">
              <ThemeIcon variant="light" size="lg">
                <IconWorld aria-hidden="true" size={20} />
              </ThemeIcon>
              <Stack gap={0}>
                <Title order={1} size="h3">
                  {t("confirmation.title")}
                </Title>
                <Text size="sm" c="dimmed">
                  {t("confirmation.subtitle")}
                </Text>
              </Stack>
            </Group>
            <Badge
              color={pending ? "yellow" : service.active ? "green" : "gray"}
            >
              {pending
                ? t("status.pending")
                : service.active
                  ? t("status.active")
                  : t("status.inactive")}
            </Badge>
          </Group>

          <Stack gap="xs">
            <Text fw={600}>{label}</Text>
            <Text size="sm" c="dimmed">
              {t("service.localPort", { port: service.endpoint.port })}
            </Text>
            <Text size="sm">
              {t("confirmation.duration", { minutes: duration })}
            </Text>
            <Text size="sm" c="dimmed">
              {t("confirmation.untrustedNotice")}
            </Text>
          </Stack>

          {state.actionError !== null ? (
            <Alert color="red">{state.actionError}</Alert>
          ) : null}

          {pending ? (
            <Group align="stretch">
              <Button
                leftSection={<IconLock size={16} />}
                loading={state.action === "approve"}
                disabled={state.action !== null}
                onClick={onApprove}
              >
                {t("actions.approveDuration", { minutes: duration })}
              </Button>
              <Button
                variant="default"
                loading={state.action === "reject"}
                disabled={state.action !== null}
                onClick={onReject}
              >
                {t("actions.reject")}
              </Button>
              <Button
                variant="subtle"
                loading={state.action === "cancel"}
                disabled={state.action !== null}
                onClick={onCancel}
              >
                {t("actions.cancel")}
              </Button>
            </Group>
          ) : (
            <Alert color={service.active ? "green" : "gray"}>
              {service.active
                ? t("confirmation.alreadyActive")
                : t("confirmation.stale")}
            </Alert>
          )}

          <Group>
            {service.endpoint.url !== null ? (
              <Button
                component="a"
                href={service.endpoint.url}
                target="_blank"
                rel="noreferrer"
                variant="light"
                rightSection={<IconExternalLink size={16} />}
              >
                {t("actions.open")}
              </Button>
            ) : null}
            {service.active && service.current_cycle !== null ? (
              <Button
                color="red"
                variant="subtle"
                loading={state.action === "close"}
                disabled={state.action !== null}
                onClick={onClose}
              >
                {t("actions.close")}
              </Button>
            ) : null}
          </Group>
        </Stack>
      </Paper>
    </Container>
  );
}
