"use client";

import {
  Alert,
  Badge,
  Button,
  CopyButton,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconExternalLink, IconWorld } from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import type { RuntimeServicesState } from "../types";
import type { RuntimeWebServiceResponse } from "@azents/public-client";

export interface RuntimeServicesPanelProps {
  state: RuntimeServicesState;
  mutating: boolean;
  preparedService: RuntimeWebServiceResponse | null;
  mutationError: string | null;
  onPrepareService: (port: number, label: string | null) => void;
  onConfirmCreate: () => void;
  onResetPreparedService: () => void;
  onApprove: (service: RuntimeWebServiceResponse) => void;
  onReject: (service: RuntimeWebServiceResponse) => void;
  onCancel: (service: RuntimeWebServiceResponse) => void;
  onRequestAgain: (service: RuntimeWebServiceResponse) => void;
  onClose: (service: RuntimeWebServiceResponse) => void;
}

type StatusColor = "gray" | "green" | "red" | "yellow";

function serviceStatus(
  service: RuntimeWebServiceResponse,
  runtimeAvailable: boolean,
  t: ReturnType<typeof useTranslations<"runtimeWeb">>,
): { color: StatusColor; label: string } {
  if (service.endpoint.configuration_state === "unconfigured") {
    return { color: "red", label: t("status.unconfigured") };
  }
  if (service.active && service.current_request?.state === "pending") {
    return { color: "green", label: t("status.activePending") };
  }
  if (service.active) {
    return {
      color: runtimeAvailable ? "green" : "yellow",
      label: runtimeAvailable ? t("status.active") : t("status.unavailable"),
    };
  }
  if (service.current_request?.state === "pending") {
    return { color: "yellow", label: t("status.pending") };
  }
  if (service.current_cycle?.end_reason === "expired") {
    return { color: "gray", label: t("status.expired") };
  }
  if (service.current_cycle?.end_reason === "closed") {
    return { color: "gray", label: t("status.closed") };
  }
  return { color: "gray", label: t("status.inactive") };
}

function formatTime(value: string, locale: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatDuration(
  service: RuntimeWebServiceResponse,
  locale: string,
): string {
  return new Intl.NumberFormat(locale).format(
    Math.round(service.duration_seconds / 60),
  );
}

export function RuntimeServicesPanel({
  state,
  mutating,
  preparedService,
  mutationError,
  onPrepareService,
  onConfirmCreate,
  onResetPreparedService,
  onApprove,
  onReject,
  onCancel,
  onRequestAgain,
  onClose,
}: RuntimeServicesPanelProps): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const locale = useLocale();
  const [createOpened, setCreateOpened] = useState(false);
  const [port, setPort] = useState<number | string>(3000);
  const [label, setLabel] = useState("");
  const [approvalService, setApprovalService] =
    useState<RuntimeWebServiceResponse | null>(null);

  const closeCreate = (): void => {
    if (mutating) {
      return;
    }
    setCreateOpened(false);
    onResetPreparedService();
  };

  if (state.type === "LOADING") {
    return (
      <Group gap="xs" p="md">
        <Loader size="xs" />
        <Text size="sm">{t("panel.loading")}</Text>
      </Group>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Alert color="red" title={t("panel.errorTitle")}>
        {state.message}
      </Alert>
    );
  }

  const validPort = typeof port === "number" && port >= 1 && port <= 65_535;

  return (
    <>
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack gap={0}>
            <Text fw={700}>{t("panel.title")}</Text>
            <Text size="sm" c="dimmed">
              {t("panel.description")}
            </Text>
          </Stack>
          <Button
            leftSection={<IconWorld size={16} />}
            onClick={() => setCreateOpened(true)}
          >
            {t("panel.create")}
          </Button>
        </Group>

        {mutationError !== null ? (
          <Alert color="red">{mutationError}</Alert>
        ) : null}

        {state.services.length === 0 ? (
          <Paper withBorder radius="md" p="lg">
            <Text fw={600}>{t("panel.emptyTitle")}</Text>
            <Text size="sm" c="dimmed">
              {t("panel.emptyDescription")}
            </Text>
          </Paper>
        ) : (
          state.services.map((service) => {
            const pending = service.current_request?.state === "pending";
            const url = service.endpoint.url;
            const status = serviceStatus(service, state.runtimeAvailable, t);
            return (
              <Paper key={service.endpoint.id} withBorder radius="md" p="md">
                <Stack gap="sm">
                  <Group
                    justify="space-between"
                    align="flex-start"
                    wrap="nowrap"
                  >
                    <Stack gap={0} style={{ minWidth: 0 }}>
                      <Text fw={600} lineClamp={1}>
                        {service.endpoint.label ??
                          t("service.portLabel", {
                            port: service.endpoint.port,
                          })}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {t("service.localPort", {
                          port: service.endpoint.port,
                        })}
                      </Text>
                    </Stack>
                    <Badge color={status.color} variant="light">
                      {status.label}
                    </Badge>
                  </Group>

                  {service.current_cycle !== null ? (
                    <Text size="xs" c="dimmed">
                      {service.active
                        ? t("service.expiresAt", {
                            time: formatTime(
                              service.current_cycle.expires_at,
                              locale,
                            ),
                          })
                        : service.current_cycle.ended_at === null
                          ? null
                          : t("service.endedAt", {
                              time: formatTime(
                                service.current_cycle.ended_at,
                                locale,
                              ),
                            })}
                    </Text>
                  ) : null}

                  {service.active && !state.runtimeAvailable ? (
                    <Alert color="yellow">{t("status.unavailable")}</Alert>
                  ) : null}

                  {url !== null ? (
                    <Text size="sm" lineClamp={1} title={url}>
                      {url}
                    </Text>
                  ) : null}

                  <Group gap="xs">
                    {pending ? (
                      <>
                        <Button
                          size="xs"
                          disabled={mutating}
                          onClick={() => setApprovalService(service)}
                        >
                          {t("actions.approve")}
                        </Button>
                        <Button
                          size="xs"
                          variant="default"
                          disabled={mutating}
                          onClick={() => onReject(service)}
                        >
                          {t("actions.reject")}
                        </Button>
                        <Button
                          size="xs"
                          variant="subtle"
                          disabled={mutating}
                          onClick={() => onCancel(service)}
                        >
                          {t("actions.cancel")}
                        </Button>
                      </>
                    ) : (
                      <Button
                        size="xs"
                        variant="default"
                        disabled={mutating}
                        onClick={() => onRequestAgain(service)}
                      >
                        {t("actions.requestAgain")}
                      </Button>
                    )}
                    {service.active && service.current_cycle !== null ? (
                      <Button
                        size="xs"
                        color="red"
                        variant="subtle"
                        disabled={mutating}
                        onClick={() => onClose(service)}
                      >
                        {t("actions.close")}
                      </Button>
                    ) : null}
                    {url !== null ? (
                      <>
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
                      </>
                    ) : null}
                  </Group>
                </Stack>
              </Paper>
            );
          })
        )}
      </Stack>

      <Modal
        opened={createOpened}
        onClose={closeCreate}
        title={
          preparedService === null
            ? t("panel.createTitle")
            : t("panel.confirmTitle")
        }
        centered
      >
        {preparedService === null ? (
          <Stack gap="md">
            {mutationError !== null ? (
              <Alert color="red">{mutationError}</Alert>
            ) : null}
            <NumberInput
              label={t("panel.port")}
              placeholder={t("panel.portPlaceholder")}
              min={1}
              max={65_535}
              value={port}
              onChange={setPort}
              required
            />
            <TextInput
              label={t("panel.label")}
              placeholder={t("panel.labelPlaceholder")}
              maxLength={120}
              value={label}
              onChange={(event) => setLabel(event.currentTarget.value)}
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={closeCreate}>
                {t("panel.cancelDialog")}
              </Button>
              <Button
                loading={mutating}
                disabled={!validPort}
                onClick={() => {
                  if (typeof port === "number") {
                    onPrepareService(port, label.trim() || null);
                  }
                }}
              >
                {t("panel.continue")}
              </Button>
            </Group>
          </Stack>
        ) : (
          <Stack gap="md">
            {mutationError !== null ? (
              <Alert color="red">{mutationError}</Alert>
            ) : null}
            <Text fw={600}>
              {preparedService.endpoint.label ??
                t("service.portLabel", {
                  port: preparedService.endpoint.port,
                })}
            </Text>
            <Text size="sm">
              {t("panel.confirmDescription", {
                minutes: formatDuration(preparedService, locale),
              })}
            </Text>
            <Text size="sm" c="dimmed">
              {t("confirmation.untrustedNotice")}
            </Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={closeCreate}>
                {t("panel.cancelDialog")}
              </Button>
              <Button
                loading={mutating}
                onClick={() => {
                  onConfirmCreate();
                  setCreateOpened(false);
                }}
              >
                {t("actions.approveDuration", {
                  minutes: formatDuration(preparedService, locale),
                })}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>

      <Modal
        opened={approvalService !== null}
        onClose={() => {
          if (!mutating) {
            setApprovalService(null);
          }
        }}
        title={t("confirmation.title")}
        centered
      >
        {approvalService !== null ? (
          <Stack gap="md">
            <Text fw={600}>
              {approvalService.current_request?.label ??
                approvalService.endpoint.label ??
                t("service.portLabel", {
                  port: approvalService.endpoint.port,
                })}
            </Text>
            <Text size="sm">
              {t("panel.confirmDescription", {
                minutes: formatDuration(approvalService, locale),
              })}
            </Text>
            <Text size="sm" c="dimmed">
              {t("confirmation.untrustedNotice")}
            </Text>
            <Group justify="flex-end">
              <Button
                variant="default"
                disabled={mutating}
                onClick={() => setApprovalService(null)}
              >
                {t("panel.cancelDialog")}
              </Button>
              <Button
                loading={mutating}
                onClick={() => {
                  onApprove(approvalService);
                  setApprovalService(null);
                }}
              >
                {t("actions.approveDuration", {
                  minutes: formatDuration(approvalService, locale),
                })}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
    </>
  );
}
