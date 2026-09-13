"use client";

import {
  Alert,
  Badge,
  Button,
  CopyButton,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
} from "@mantine/core";
import { IconExternalLink, IconWorld } from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import type { RuntimeWebServiceResponse } from "@azents/public-client";

export type RuntimeWebRequestCardState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      service: RuntimeWebServiceResponse;
      stale: boolean;
      action: "approve" | "reject" | "cancel" | "close" | null;
      actionError: string | null;
    };

export interface RuntimeWebServiceRequestCardProps {
  state: RuntimeWebRequestCardState;
  fallbackLabel: string | null;
  fallbackPort: number;
  fallbackUrl: string;
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
  onClose: () => void;
}

function statusColor(
  service: RuntimeWebServiceResponse,
): "gray" | "green" | "yellow" {
  return service.active
    ? "green"
    : service.current_request?.state === "pending"
      ? "yellow"
      : "gray";
}

export function RuntimeWebServiceRequestCard({
  state,
  fallbackLabel,
  fallbackPort,
  fallbackUrl,
  onApprove,
  onReject,
  onCancel,
  onClose,
}: RuntimeWebServiceRequestCardProps): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const locale = useLocale();
  if (state.type === "LOADING") {
    return (
      <Paper withBorder radius="md" p="md">
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm">{t("confirmation.loading")}</Text>
        </Group>
      </Paper>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red" title={t("confirmation.errorTitle")}>
        {state.message}
      </Alert>
    );
  }

  const service = state.service;
  const pending = service.current_request?.state === "pending";
  const duration = new Intl.NumberFormat(locale).format(
    Math.round(service.duration_seconds / 60),
  );
  const label =
    service.current_request?.label ??
    service.endpoint.label ??
    fallbackLabel ??
    t("service.portLabel", { port: fallbackPort });
  const url = service.endpoint.url ?? fallbackUrl;
  const status = service.active
    ? pending
      ? t("status.activePending")
      : t("status.active")
    : pending
      ? t("status.pending")
      : t("status.inactive");

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <IconWorld aria-hidden="true" size={18} />
            <Stack gap={0} style={{ minWidth: 0 }}>
              <Text fw={600} lineClamp={1}>
                {label}
              </Text>
              <Text size="xs" c="dimmed">
                {t("service.localPort", { port: service.endpoint.port })}
              </Text>
            </Stack>
          </Group>
          <Badge color={statusColor(service)} variant="light">
            {status}
          </Badge>
        </Group>

        <Text size="sm">
          {t("confirmation.duration", { minutes: duration })}
        </Text>
        {state.stale ? <Alert color="gray">{t("chat.stale")}</Alert> : null}
        {state.actionError !== null ? (
          <Alert color="red">{state.actionError}</Alert>
        ) : null}

        <Group gap="xs">
          {pending && !state.stale ? (
            <>
              <Button
                size="xs"
                loading={state.action === "approve"}
                disabled={state.action !== null}
                onClick={onApprove}
              >
                {t("actions.approveDuration", { minutes: duration })}
              </Button>
              <Button
                size="xs"
                variant="default"
                loading={state.action === "reject"}
                disabled={state.action !== null}
                onClick={onReject}
              >
                {t("actions.reject")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                loading={state.action === "cancel"}
                disabled={state.action !== null}
                onClick={onCancel}
              >
                {t("actions.cancel")}
              </Button>
            </>
          ) : null}
          {service.active && !state.stale ? (
            <Button
              size="xs"
              color="red"
              variant="subtle"
              loading={state.action === "close"}
              disabled={state.action !== null}
              onClick={onClose}
            >
              {t("actions.close")}
            </Button>
          ) : null}
          <CopyButton value={url}>
            {({ copied, copy }) => (
              <Button size="xs" variant="subtle" onClick={copy}>
                {copied ? t("actions.copied") : t("actions.copy")}
              </Button>
            )}
          </CopyButton>
          <Button
            component="a"
            href={url}
            target="_blank"
            rel="noreferrer"
            size="xs"
            variant="subtle"
            rightSection={<IconExternalLink size={14} />}
          >
            {t("actions.open")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}
