"use client";

import {
  Alert,
  Badge,
  Button,
  Container,
  Group,
  Loader,
  Paper,
  rem,
  Select,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconPower, IconWorld } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { RuntimeWebActivationContainerOutput } from "../containers/useRuntimeWebActivationContainer";
import type { RuntimeWebDurationSeconds } from "../types";

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

export function RuntimeWebActivation({
  state,
  onTurnOn,
  onRetry,
}: RuntimeWebActivationContainerOutput): React.ReactElement {
  const t = useTranslations("runtimeWeb");
  const [duration, setDuration] = useState<RuntimeWebDurationSeconds>(3600);

  useEffect(() => {
    if (state.type === "READY") {
      setDuration(state.service.selected_duration_seconds);
    }
  }, [state]);

  if (state.type === "LOADING") {
    return (
      <Container size="xs" py="xl">
        <Group justify="center">
          <Loader size="sm" />
          <Text size="sm">{t("activation.loading")}</Text>
        </Group>
      </Container>
    );
  }
  if (state.type === "ERROR") {
    return (
      <Container size="xs" py="xl">
        <Alert color="red" title={t("activation.errorTitle")}>
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
  return (
    <Container size="sm" py={{ base: "lg", sm: "xl" }}>
      <Paper withBorder radius="lg" p={{ base: "md", sm: "xl" }}>
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start">
            <Group gap="sm" wrap="nowrap">
              <ThemeIcon variant="light" size="lg">
                <IconWorld aria-hidden="true" size={rem(20)} />
              </ThemeIcon>
              <Stack gap={0}>
                <Title order={1} size="h3">
                  {t("activation.title")}
                </Title>
                <Text size="sm" c="dimmed">
                  {t("activation.subtitle")}
                </Text>
              </Stack>
            </Group>
            <Badge color={service.on ? "green" : "gray"}>
              {service.on ? t("status.on") : t("status.off")}
            </Badge>
          </Group>

          <Stack gap="xs">
            <Text fw={600}>
              {service.label ?? t("service.portLabel", { port: service.port })}
            </Text>
            <Text size="sm" c="dimmed">
              {t("service.localPort", { port: service.port })}
            </Text>
            <Text size="sm" c="dimmed">
              {t("activation.untrustedNotice")}
            </Text>
          </Stack>

          {state.actionError !== null ? (
            <Alert color="red">{state.actionError}</Alert>
          ) : null}

          {service.on ? (
            <Stack gap="sm">
              <Alert color="green">{t("activation.alreadyOn")}</Alert>
              {service.url !== null ? (
                <Button
                  component="a"
                  href={service.url}
                  rightSection={<IconExternalLink size={rem(16)} />}
                >
                  {t("actions.open")}
                </Button>
              ) : null}
            </Stack>
          ) : (
            <Stack gap="md">
              <Select
                allowDeselect={false}
                data={[
                  { value: "3600", label: t("duration.oneHour") },
                  { value: "21600", label: t("duration.sixHours") },
                  { value: "86400", label: t("duration.twentyFourHours") },
                ]}
                label={t("panel.duration")}
                value={String(duration)}
                onChange={(value) => {
                  const selected = durationValue(value);
                  if (selected !== null) {
                    setDuration(selected);
                  }
                }}
              />
              <Button
                leftSection={<IconPower size={rem(16)} />}
                loading={state.action === "turnOn"}
                disabled={state.action !== null}
                onClick={() => onTurnOn(duration)}
              >
                {t("actions.turnOn")}
              </Button>
            </Stack>
          )}
        </Stack>
      </Paper>
    </Container>
  );
}
