"use client";

import {
  Alert,
  Badge,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Modal,
  Paper,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconBrandDiscord,
  IconBrandSlack,
  IconLinkOff,
  IconPlugConnected,
  IconRefresh,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { ElevationView } from "@/features/security/components/ElevationView";
import { accountLinkStatusColor } from "../presentation";
import type { ExternalAccountLinksContainerProps } from "../containers/useExternalAccountLinksContainer";
import type {
  AccountLinkFailureReason,
  ExternalAccountLinkItem,
} from "../types";

type Translator = ReturnType<typeof useTranslations<"externalAccountLinks">>;

function errorMessage(reason: AccountLinkFailureReason, t: Translator): string {
  return t(`errors.${reason}`);
}

function formatDateTime(value: string, locale: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function LinkCard({
  link,
  onDisconnect,
}: {
  link: ExternalAccountLinkItem;
  onDisconnect: (link: ExternalAccountLinkItem) => void;
}): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  const locale = useLocale();
  const ProviderIcon =
    link.provider === "discord" ? IconBrandDiscord : IconBrandSlack;
  const canDisconnect = link.status !== "revoked";

  return (
    <Paper
      withBorder
      radius="lg"
      p={{ base: "md", sm: "lg" }}
      data-testid={`external-account-link-${link.id}`}
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon variant="light" size="lg" radius="md">
              <ProviderIcon aria-hidden="true" size={20} />
            </ThemeIcon>
            <Stack gap={rem(2)} style={{ minWidth: 0 }}>
              <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                {link.externalDisplayLabel}
              </Text>
              <Text size="sm" c="dimmed" style={{ overflowWrap: "anywhere" }}>
                {t("providerTeam", {
                  provider: t(`providers.${link.provider}`),
                  team: link.providerTeamLabel,
                })}
              </Text>
            </Stack>
          </Group>
          <Badge color={accountLinkStatusColor(link.status)} variant="light">
            {t(`status.${link.status}`)}
          </Badge>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
          <Stack gap={rem(2)}>
            <Text size="xs" c="dimmed">
              {t("workspace")}
            </Text>
            <Text size="sm" fw={500}>
              {link.workspaceName}
            </Text>
          </Stack>
          <Stack gap={rem(2)}>
            <Text size="xs" c="dimmed">
              {t("linkedAt")}
            </Text>
            <Text size="sm">{formatDateTime(link.linkedAt, locale)}</Text>
          </Stack>
        </SimpleGrid>

        {link.status === "inactive" ? (
          <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
            {t("inactiveDescription")}
          </Alert>
        ) : null}

        <Group justify="flex-end">
          <Button
            variant="light"
            color="red"
            leftSection={<IconLinkOff size={16} />}
            disabled={!canDisconnect}
            onClick={() => onDisconnect(link)}
          >
            {link.status === "revoked" ? t("disconnected") : t("disconnect")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function DisconnectModal({
  disconnect,
  onCancel,
  onConfirm,
}: {
  disconnect: Extract<
    Extract<
      ExternalAccountLinksContainerProps["state"],
      { type: "READY" }
    >["disconnect"],
    { type: "CONFIRMING" | "SUBMITTING" }
  >;
  onCancel: () => void;
  onConfirm: () => void;
}): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  const submitting = disconnect.type === "SUBMITTING";
  const error = disconnect.type === "CONFIRMING" ? disconnect.error : null;

  return (
    <Modal
      opened
      onClose={onCancel}
      title={t("disconnectDialog.title")}
      centered
      closeOnClickOutside={!submitting}
      closeOnEscape={!submitting}
    >
      <Stack gap="md">
        <Text size="sm">
          {t("disconnectDialog.description", {
            account: disconnect.link.externalDisplayLabel,
            workspace: disconnect.link.workspaceName,
          })}
        </Text>
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
          {t("disconnectDialog.impact")}
        </Alert>
        {error !== null ? (
          <Alert color="red" role="alert">
            {errorMessage(error, t)}
          </Alert>
        ) : null}
        <Group justify="flex-end" wrap="wrap">
          <Button variant="default" disabled={submitting} onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button color="red" loading={submitting} onClick={onConfirm}>
            {t("disconnectDialog.confirm")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function ExternalAccountLinks({
  state,
  onRequestDisconnect,
  onCancelDisconnect,
  onConfirmDisconnect,
  onRetry,
}: ExternalAccountLinksContainerProps): React.ReactElement {
  const t = useTranslations("externalAccountLinks");

  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Stack align="center" gap="sm" aria-live="polite">
            <Loader />
            <Text c="dimmed">{t("loading")}</Text>
          </Stack>
        </Center>
      );
    case "ERROR":
      return (
        <Container size="sm" py="xl">
          <Alert color="red" title={t("loadErrorTitle")} role="alert">
            <Stack gap="sm">
              <Text size="sm">{state.message}</Text>
              <Button
                variant="light"
                leftSection={<IconRefresh size={16} />}
                onClick={onRetry}
              >
                {t("retry")}
              </Button>
            </Stack>
          </Alert>
        </Container>
      );
    case "ELEVATION_REQUIRED":
      return (
        <Stack gap={0}>
          <Container size="sm" pt="xl">
            <Alert color="blue" icon={<IconPlugConnected size={16} />}>
              {t("elevationDisconnect", {
                account: state.link.externalDisplayLabel,
                workspace: state.link.workspaceName,
              })}
            </Alert>
          </Container>
          <ElevationView {...state.elevation} />
        </Stack>
      );
    case "ELEVATION_LOADING":
      return (
        <Center py="xl">
          <Stack align="center" gap="sm" aria-live="polite">
            <Loader />
            <Text c="dimmed">{t("elevationLoading")}</Text>
          </Stack>
        </Center>
      );
    case "ELEVATION_ERROR":
      return (
        <Container size="sm" py="xl">
          <Alert color="red" title={t("elevationErrorTitle")} role="alert">
            <Stack gap="sm">
              <Text size="sm">{state.message}</Text>
              <Button
                variant="light"
                leftSection={<IconRefresh size={16} />}
                onClick={onRetry}
              >
                {t("retry")}
              </Button>
            </Stack>
          </Alert>
        </Container>
      );
    case "READY":
      return (
        <Container
          size="md"
          py={{ base: "lg", sm: "xl" }}
          data-testid="external-account-links"
        >
          <Stack gap="lg">
            <Stack gap={rem(4)}>
              <Title order={1} size="h2">
                {t("title")}
              </Title>
              <Text c="dimmed">{t("description")}</Text>
            </Stack>

            {state.links.length === 0 ? (
              <Paper withBorder radius="lg" p="xl">
                <Stack align="center" gap="sm" ta="center">
                  <ThemeIcon variant="light" size="xl" radius="xl">
                    <IconPlugConnected size={22} />
                  </ThemeIcon>
                  <Text fw={600}>{t("emptyTitle")}</Text>
                  <Text c="dimmed" size="sm">
                    {t("emptyDescription")}
                  </Text>
                </Stack>
              </Paper>
            ) : (
              <Stack gap="md">
                {state.links.map((link) => (
                  <LinkCard
                    key={link.id}
                    link={link}
                    onDisconnect={onRequestDisconnect}
                  />
                ))}
              </Stack>
            )}
          </Stack>

          {state.disconnect.type !== "IDLE" ? (
            <DisconnectModal
              disconnect={state.disconnect}
              onCancel={onCancelDisconnect}
              onConfirm={onConfirmDisconnect}
            />
          ) : null}
        </Container>
      );
  }
}
