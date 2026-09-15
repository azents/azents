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
  rem,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconExternalLink,
  IconPencil,
  IconRefresh,
  IconTrash,
  IconWorld,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import type { RuntimeWebServicesContainerOutput } from "../containers/useRuntimeWebServicesContainer";
import type { RuntimeWebDurationSeconds } from "../types";
import type { RuntimeWebServiceResponse } from "@azents/public-client";

export type RuntimeWebServicesProps = RuntimeWebServicesContainerOutput;

function durationValue(value: string | null): RuntimeWebDurationSeconds | null {
  switch (value) {
    case "3600":
      return 3600;
    case "21600":
      return 21_600;
    case "86400":
      return 86_400;
    default:
      return null;
  }
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

export function RuntimeWebServices({
  state,
  action,
  mutationError,
  onCreate,
  onUpdate,
  onTurnOn,
  onTurnOff,
  onReset,
  onDelete,
}: RuntimeWebServicesProps): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const locale = useLocale();
  const [createOpened, setCreateOpened] = useState(false);
  const [port, setPort] = useState<number | string>(3000);
  const [label, setLabel] = useState("");
  const [duration, setDuration] = useState<RuntimeWebDurationSeconds>(3600);
  const [turnOn, setTurnOn] = useState(false);
  const [editing, setEditing] = useState<RuntimeWebServiceResponse | null>(
    null,
  );
  const [editLabel, setEditLabel] = useState("");
  const [editDuration, setEditDuration] =
    useState<RuntimeWebDurationSeconds>(3600);
  const [deleting, setDeleting] = useState<RuntimeWebServiceResponse | null>(
    null,
  );
  const submittedAction = useRef<"create" | "update" | "delete" | null>(null);

  useEffect(() => {
    if (action !== null || mutationError !== null) {
      return;
    }
    if (submittedAction.current === "create") {
      setCreateOpened(false);
      setPort(3000);
      setLabel("");
      setDuration(3600);
      setTurnOn(false);
    } else if (submittedAction.current === "update") {
      setEditing(null);
    } else if (submittedAction.current === "delete") {
      setDeleting(null);
    }
    submittedAction.current = null;
  }, [action, mutationError]);

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
  const mutating = action !== null;
  const durationOptions = [
    { value: "3600", label: t("duration.oneHour") },
    { value: "21600", label: t("duration.sixHours") },
    { value: "86400", label: t("duration.twentyFourHours") },
  ];

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
            leftSection={<IconWorld size={rem(16)} />}
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
          state.services.map((service) => (
            <Paper key={service.id} withBorder radius="md" p="md">
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <Stack gap={0} style={{ minWidth: 0 }}>
                    <Text fw={600} lineClamp={1}>
                      {service.label ??
                        t("service.portLabel", { port: service.port })}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {t("service.localPort", { port: service.port })}
                    </Text>
                  </Stack>
                  <Badge
                    color={
                      service.configuration_state === "unconfigured"
                        ? "red"
                        : service.on
                          ? "green"
                          : "gray"
                    }
                    variant="light"
                  >
                    {service.configuration_state === "unconfigured"
                      ? t("status.unconfigured")
                      : service.on
                        ? t("status.on")
                        : t("status.off")}
                  </Badge>
                </Group>

                <Group gap="xs">
                  <Badge variant="outline">
                    {t(
                      `duration.${
                        service.selected_duration_seconds === 3600
                          ? "oneHour"
                          : service.selected_duration_seconds === 21_600
                            ? "sixHours"
                            : "twentyFourHours"
                      }`,
                    )}
                  </Badge>
                  {service.on && service.expires_at !== null ? (
                    <Text size="xs" c="dimmed">
                      {t("service.expiresAt", {
                        time: formatTime(service.expires_at, locale),
                      })}
                    </Text>
                  ) : null}
                </Group>

                {service.on && !state.runtimeAvailable ? (
                  <Alert color="yellow">{t("status.runtimeUnavailable")}</Alert>
                ) : null}

                {service.url !== null ? (
                  <Text size="sm" lineClamp={1} title={service.url}>
                    {service.url}
                  </Text>
                ) : null}

                <Group gap="xs">
                  {service.on ? (
                    <Button
                      size="xs"
                      variant="default"
                      disabled={mutating}
                      loading={action === "turnOff"}
                      onClick={() => onTurnOff(service)}
                    >
                      {t("actions.turnOff")}
                    </Button>
                  ) : (
                    <Button
                      size="xs"
                      disabled={
                        mutating ||
                        service.configuration_state === "unconfigured"
                      }
                      loading={action === "turnOn"}
                      onClick={() =>
                        onTurnOn(service, service.selected_duration_seconds)
                      }
                    >
                      {t("actions.turnOn")}
                    </Button>
                  )}
                  {service.on ? (
                    <Button
                      size="xs"
                      variant="subtle"
                      disabled={mutating}
                      loading={action === "reset"}
                      leftSection={<IconRefresh size={rem(14)} />}
                      onClick={() => onReset(service)}
                    >
                      {t("actions.resetExpiration")}
                    </Button>
                  ) : null}
                  <Button
                    size="xs"
                    variant="subtle"
                    disabled={mutating}
                    leftSection={<IconPencil size={rem(14)} />}
                    onClick={() => {
                      setEditing(service);
                      setEditLabel(service.label ?? "");
                      setEditDuration(service.selected_duration_seconds);
                    }}
                  >
                    {t("actions.edit")}
                  </Button>
                  <Button
                    size="xs"
                    color="red"
                    variant="subtle"
                    disabled={mutating}
                    leftSection={<IconTrash size={rem(14)} />}
                    onClick={() => setDeleting(service)}
                  >
                    {t("actions.delete")}
                  </Button>
                  {service.url !== null ? (
                    <>
                      <CopyButton value={service.url}>
                        {({ copied, copy }) => (
                          <Button size="xs" variant="subtle" onClick={copy}>
                            {copied ? t("actions.copied") : t("actions.copy")}
                          </Button>
                        )}
                      </CopyButton>
                      <Button
                        component="a"
                        href={service.url}
                        target="_blank"
                        rel="noreferrer"
                        size="xs"
                        variant="subtle"
                        rightSection={<IconExternalLink size={rem(14)} />}
                      >
                        {t("actions.open")}
                      </Button>
                    </>
                  ) : null}
                </Group>
              </Stack>
            </Paper>
          ))
        )}
      </Stack>

      <Modal
        opened={createOpened}
        onClose={() => {
          if (!mutating) {
            setCreateOpened(false);
          }
        }}
        title={t("panel.createTitle")}
        centered
      >
        <Stack gap="md">
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
          <Select
            allowDeselect={false}
            data={durationOptions}
            label={t("panel.duration")}
            value={String(duration)}
            onChange={(value) => {
              const selected = durationValue(value);
              if (selected !== null) {
                setDuration(selected);
              }
            }}
          />
          <Switch
            checked={turnOn}
            label={t("panel.turnOnAfterCreate")}
            onChange={(event) => setTurnOn(event.currentTarget.checked)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setCreateOpened(false)}>
              {t("panel.cancelDialog")}
            </Button>
            <Button
              loading={action === "create"}
              disabled={!validPort || mutating}
              onClick={() => {
                if (typeof port !== "number") {
                  return;
                }
                submittedAction.current = "create";
                onCreate({
                  port,
                  label: label.trim() || null,
                  selectedDurationSeconds: duration,
                  turnOn,
                });
              }}
            >
              {t("panel.create")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={editing !== null}
        onClose={() => {
          if (!mutating) {
            setEditing(null);
          }
        }}
        title={t("panel.editTitle")}
        centered
      >
        {editing !== null ? (
          <Stack gap="md">
            <TextInput
              label={t("panel.label")}
              maxLength={120}
              value={editLabel}
              onChange={(event) => setEditLabel(event.currentTarget.value)}
            />
            <Select
              allowDeselect={false}
              data={durationOptions}
              label={t("panel.duration")}
              value={String(editDuration)}
              onChange={(value) => {
                const selected = durationValue(value);
                if (selected !== null) {
                  setEditDuration(selected);
                }
              }}
            />
            {editing.on &&
            editDuration !== editing.selected_duration_seconds ? (
              <Alert color="blue">{t("panel.durationDeferred")}</Alert>
            ) : null}
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setEditing(null)}>
                {t("panel.cancelDialog")}
              </Button>
              <Button
                loading={action === "update"}
                disabled={mutating}
                onClick={() => {
                  submittedAction.current = "update";
                  onUpdate(editing, {
                    label: editLabel.trim() || null,
                    selectedDurationSeconds: editDuration,
                  });
                }}
              >
                {t("actions.save")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>

      <Modal
        opened={deleting !== null}
        onClose={() => {
          if (!mutating) {
            setDeleting(null);
          }
        }}
        title={t("panel.deleteTitle")}
        centered
      >
        {deleting !== null ? (
          <Stack gap="md">
            <Text size="sm">{t("panel.deleteDescription")}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDeleting(null)}>
                {t("panel.cancelDialog")}
              </Button>
              <Button
                color="red"
                loading={action === "delete"}
                disabled={mutating}
                onClick={() => {
                  submittedAction.current = "delete";
                  onDelete(deleting);
                }}
              >
                {t("actions.delete")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
    </>
  );
}
