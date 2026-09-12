"use client";

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Center,
  Code,
  Container,
  CopyButton,
  Divider,
  Group,
  Loader,
  Paper,
  rem,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconBrandDiscord,
  IconBrandSlack,
  IconCheck,
  IconCopy,
  IconExternalLink,
  IconRefresh,
  IconSwitchHorizontal,
  IconUserCheck,
  IconX,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import { ElevationView } from "@/features/security/components/ElevationView";
import { candidateNextAction } from "../presentation";
import type { ExternalAccountLinkConfirmationContainerProps } from "../containers/useExternalAccountLinkConfirmationContainer";
import type {
  AccountLinkFailureReason,
  ExternalAccountLinkOrigin,
} from "../types";

type Translator = ReturnType<typeof useTranslations<"externalAccountLinks">>;

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

function errorMessage(reason: AccountLinkFailureReason, t: Translator): string {
  return t(`errors.${reason}`);
}

function DetailRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="lg">
      <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
        {label}
      </Text>
      <Text
        size="sm"
        fw={500}
        ta="right"
        style={{ minWidth: 0, overflowWrap: "anywhere" }}
      >
        {value}
      </Text>
    </Group>
  );
}

function IdentityContext({
  origin,
  accountEmail,
}: {
  origin: ExternalAccountLinkOrigin;
  accountEmail: string;
}): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  const ProviderIcon =
    origin.provider === "discord" ? IconBrandDiscord : IconBrandSlack;

  return (
    <Paper
      withBorder
      radius="lg"
      p={{ base: "md", sm: "lg" }}
      data-testid="external-link-context"
    >
      <Stack gap="md">
        <Group gap="sm" wrap="nowrap">
          <ThemeIcon variant="light" size="lg" radius="md">
            <ProviderIcon aria-hidden="true" size={20} />
          </ThemeIcon>
          <Stack gap={rem(2)}>
            <Text fw={600}>{t("confirmation.accountPair")}</Text>
            <Text size="sm" c="dimmed">
              {t("confirmation.accountPairDescription")}
            </Text>
          </Stack>
        </Group>
        <Divider />
        <Stack gap="sm">
          <DetailRow label={t("workspace")} value={origin.workspaceName} />
          <DetailRow
            label={t("confirmation.externalAccount")}
            value={origin.externalDisplayLabel}
          />
          <DetailRow
            label={t("confirmation.providerTeam")}
            value={`${t(`providers.${origin.provider}`)} · ${origin.providerTeamLabel}`}
          />
          <DetailRow
            label={t("confirmation.azentsAccount")}
            value={accountEmail}
          />
        </Stack>
      </Stack>
    </Paper>
  );
}

function StateMessage({
  title,
  description,
  onRetry,
}: {
  title: string;
  description: string;
  onRetry?: () => void;
}): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  return (
    <Container size="xs" py="xl">
      <Paper withBorder radius="lg" p="xl">
        <Stack align="center" gap="md" ta="center">
          <ThemeIcon color="gray" variant="light" size="xl" radius="xl">
            <IconX size={22} />
          </ThemeIcon>
          <Stack gap={rem(4)}>
            <Title order={1} size="h3">
              {title}
            </Title>
            <Text c="dimmed" size="sm">
              {description}
            </Text>
          </Stack>
          {typeof onRetry === "function" ? (
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              onClick={onRetry}
            >
              {t("retry")}
            </Button>
          ) : null}
        </Stack>
      </Paper>
    </Container>
  );
}

function ReadyConfirmation({
  state,
  onCreateCandidate,
  onCheckStatus,
  onConfirmLink,
  onStartFresh,
  onCancel,
  onSwitchAccount,
}: Pick<
  ExternalAccountLinkConfirmationContainerProps,
  | "onCreateCandidate"
  | "onCheckStatus"
  | "onConfirmLink"
  | "onStartFresh"
  | "onCancel"
  | "onSwitchAccount"
> & {
  state: Extract<
    ExternalAccountLinkConfirmationContainerProps["state"],
    { type: "READY" }
  >;
}): React.ReactElement {
  const t = useTranslations("externalAccountLinks");
  const locale = useLocale();
  const busy = state.action.type !== "IDLE";
  const actionError = state.action.type === "IDLE" ? state.action.error : null;
  const nextAction =
    state.candidate === null
      ? null
      : candidateNextAction(state.candidate.status);

  return (
    <Container size="sm" py={{ base: "lg", sm: "xl" }}>
      <Stack gap="lg">
        <Stack gap={rem(4)}>
          <Title order={1} size="h2">
            {t("confirmation.title")}
          </Title>
          <Text c="dimmed">{t("confirmation.description")}</Text>
        </Stack>

        <IdentityContext
          origin={state.origin}
          accountEmail={state.accountEmail}
        />

        {state.candidate === null ? (
          <Paper withBorder radius="lg" p={{ base: "md", sm: "lg" }}>
            <Stack gap="md">
              <Alert color="blue" icon={<IconAlertTriangle size={16} />}>
                {t("confirmation.beforeCode")}
              </Alert>
              <Button
                leftSection={<IconUserCheck size={18} />}
                loading={state.action.type === "CREATING_CANDIDATE"}
                disabled={busy}
                onClick={onCreateCandidate}
                size="md"
              >
                {t("confirmation.createCode")}
              </Button>
            </Stack>
          </Paper>
        ) : (
          <Paper
            withBorder
            radius="lg"
            p={{ base: "md", sm: "lg" }}
            data-testid="external-link-status"
          >
            <Stack gap="md">
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={rem(2)}>
                  <Text fw={600}>{t("confirmation.codeTitle")}</Text>
                  <Text size="sm" c="dimmed">
                    {t("confirmation.codeExpires", {
                      time: formatDateTime(state.candidate.expiresAt, locale),
                    })}
                  </Text>
                </Stack>
                <Badge
                  color={
                    state.candidate.status === "provider_verified"
                      ? "green"
                      : state.candidate.status === "pending_provider_proof"
                        ? "blue"
                        : "gray"
                  }
                  variant="light"
                >
                  {t(`candidateStatus.${state.candidate.status}`)}
                </Badge>
              </Group>

              <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
                {t("confirmation.codeSafety")}
              </Alert>

              <Group
                justify="space-between"
                align="center"
                wrap="nowrap"
                gap="sm"
                data-testid="external-link-code"
              >
                <Code
                  fz="lg"
                  fw={700}
                  p="sm"
                  style={{
                    flex: 1,
                    minWidth: 0,
                    overflowWrap: "anywhere",
                    textAlign: "center",
                    letterSpacing: rem(1),
                  }}
                >
                  {state.candidate.code}
                </Code>
                <CopyButton value={state.candidate.code} timeout={1600}>
                  {({ copied, copy }): React.ReactElement => (
                    <Button
                      variant="default"
                      aria-label={
                        copied
                          ? t("confirmation.copied")
                          : t("confirmation.copyCode")
                      }
                      leftSection={
                        copied ? (
                          <IconCheck size={16} />
                        ) : (
                          <IconCopy size={16} />
                        )
                      }
                      onClick={copy}
                    >
                      {copied
                        ? t("confirmation.copied")
                        : t("confirmation.copy")}
                    </Button>
                  )}
                </CopyButton>
              </Group>

              <Text size="sm">{t("confirmation.enterInProvider")}</Text>

              {nextAction === "check_status" ? (
                <Button
                  variant="light"
                  leftSection={<IconRefresh size={16} />}
                  loading={state.action.type === "CHECKING_STATUS"}
                  disabled={busy}
                  onClick={onCheckStatus}
                >
                  {t("confirmation.checkStatus")}
                </Button>
              ) : null}

              {nextAction === "confirm" ? (
                <>
                  <Alert color="green" icon={<IconCheck size={16} />}>
                    {t("confirmation.providerVerified")}
                  </Alert>
                  <Button
                    leftSection={<IconUserCheck size={18} />}
                    loading={state.action.type === "CONFIRMING_LINK"}
                    disabled={busy}
                    onClick={onConfirmLink}
                    data-testid="external-link-final-confirm"
                  >
                    {t("confirmation.confirm")}
                  </Button>
                </>
              ) : null}

              {nextAction === "start_fresh" ? (
                <Button
                  variant="light"
                  leftSection={<IconRefresh size={16} />}
                  loading={state.action.type === "CANCELLING"}
                  disabled={busy}
                  onClick={onStartFresh}
                >
                  {t("confirmation.startFresh")}
                </Button>
              ) : null}
            </Stack>
          </Paper>
        )}

        {actionError !== null ? (
          <Alert color="red" role="alert">
            {errorMessage(actionError, t)}
          </Alert>
        ) : null}

        <Group justify="space-between" wrap="wrap">
          <Button
            variant="subtle"
            color="gray"
            disabled={busy}
            onClick={onCancel}
          >
            {t("cancel")}
          </Button>
          <Button
            variant="default"
            leftSection={<IconSwitchHorizontal size={16} />}
            loading={state.action.type === "SWITCHING_ACCOUNT"}
            disabled={busy}
            onClick={onSwitchAccount}
          >
            {t("confirmation.switchAccount")}
          </Button>
        </Group>
      </Stack>
    </Container>
  );
}

export function ExternalAccountLinkConfirmation({
  state,
  onCreateCandidate,
  onCheckStatus,
  onConfirmLink,
  onStartFresh,
  onCancel,
  onSwitchAccount,
  onReturn,
  onRetry,
}: ExternalAccountLinkConfirmationContainerProps): React.ReactElement {
  const t = useTranslations("externalAccountLinks");

  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Stack align="center" gap="sm" aria-live="polite">
            <Loader />
            <Text c="dimmed">{t("confirmation.loading")}</Text>
          </Stack>
        </Center>
      );
    case "NOT_FOUND":
      return (
        <StateMessage
          title={t("confirmation.notFoundTitle")}
          description={t("confirmation.notFoundDescription")}
        />
      );
    case "ORIGIN_UNAVAILABLE":
      return (
        <Container size="sm" py="xl">
          <Stack gap="md">
            <IdentityContext
              origin={state.origin}
              accountEmail={state.accountEmail}
            />
            <Paper withBorder radius="lg" p="xl">
              <Stack align="center" gap="md" ta="center">
                <ThemeIcon color="gray" variant="light" size="xl" radius="xl">
                  <IconX size={22} />
                </ThemeIcon>
                <Stack gap={rem(4)}>
                  <Title order={1} size="h3">
                    {t(`confirmation.origin.${state.reason}.title`)}
                  </Title>
                  <Text c="dimmed" size="sm">
                    {t(`confirmation.origin.${state.reason}.description`)}
                  </Text>
                </Stack>
                <Button
                  variant="light"
                  leftSection={<IconExternalLink size={16} />}
                  onClick={onReturn}
                >
                  {t("confirmation.return")}
                </Button>
              </Stack>
            </Paper>
          </Stack>
        </Container>
      );
    case "ORIGIN_EXPIRED":
      return (
        <StateMessage
          title={t("confirmation.origin.expired.title")}
          description={t("confirmation.origin.expired.description")}
        />
      );
    case "ERROR":
      return (
        <StateMessage
          title={t("confirmation.errorTitle")}
          description={state.message || t("confirmation.errorDescription")}
          onRetry={onRetry}
        />
      );
    case "ELEVATION_REQUIRED":
      return (
        <Stack gap={0}>
          <Container size="sm" pt="xl">
            <IdentityContext
              origin={state.origin}
              accountEmail={state.accountEmail}
            />
            <Alert color="blue" mt="md">
              {state.action === "create_candidate"
                ? t("confirmation.elevationCreate")
                : t("confirmation.elevationConfirm")}
            </Alert>
          </Container>
          <ElevationView {...state.elevation} />
        </Stack>
      );
    case "ELEVATION_LOADING":
      return (
        <Container size="sm" py="xl">
          <IdentityContext
            origin={state.origin}
            accountEmail={state.accountEmail}
          />
          <Stack align="center" gap="sm" py="xl" aria-live="polite">
            <Loader />
            <Text c="dimmed">{t("elevationLoading")}</Text>
          </Stack>
        </Container>
      );
    case "ELEVATION_ERROR":
      return (
        <Container size="sm" py="xl">
          <Stack gap="md">
            <IdentityContext
              origin={state.origin}
              accountEmail={state.accountEmail}
            />
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
          </Stack>
        </Container>
      );
    case "CONNECTED":
      return (
        <Container size="sm" py={{ base: "lg", sm: "xl" }}>
          <Paper
            withBorder
            radius="lg"
            p={{ base: "lg", sm: "xl" }}
            data-testid="external-link-status"
          >
            <Stack align="center" gap="lg" ta="center">
              <ThemeIcon color="green" variant="light" size="xl" radius="xl">
                <IconCheck size={24} />
              </ThemeIcon>
              <Stack gap={rem(4)}>
                <Title order={1} size="h2">
                  {t("confirmation.connectedTitle")}
                </Title>
                <Text c="dimmed">
                  {t("confirmation.connectedDescription", {
                    account: state.externalDisplayLabel,
                    workspace: state.workspaceName,
                  })}
                </Text>
              </Stack>
              <Alert color="blue">{t("confirmation.connectedImpact")}</Alert>
              <Button
                leftSection={<IconExternalLink size={16} />}
                onClick={onReturn}
              >
                {t("confirmation.return")}
              </Button>
              <Anchor href="/account/external-accounts" size="sm">
                {t("confirmation.manage")}
              </Anchor>
            </Stack>
          </Paper>
        </Container>
      );
    case "READY":
      return (
        <ReadyConfirmation
          state={state}
          onCreateCandidate={onCreateCandidate}
          onCheckStatus={onCheckStatus}
          onConfirmLink={onConfirmLink}
          onStartFresh={onStartFresh}
          onCancel={onCancel}
          onSwitchAccount={onSwitchAccount}
        />
      );
  }
}
