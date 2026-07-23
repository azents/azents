"use client";

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Container,
  CopyButton,
  Divider,
  Group,
  Loader,
  Paper,
  rem,
  SimpleGrid,
  Stack,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconBan,
  IconBrandSlack,
  IconCheck,
  IconCopy,
  IconExternalLink,
  IconLock,
  IconRefresh,
  IconUser,
  IconUsers,
  IconX,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import type { ExternalChannelApprovalContainerOutput } from "../containers/useExternalChannelApprovalContainer";
import type {
  ExternalChannelApprovalDecision,
  ExternalChannelApprovalState,
} from "../types";
import type { ManagedApprovalRequest } from "@azents/public-client";

type ApprovalTranslator = ReturnType<
  typeof useTranslations<"externalChannelApproval">
>;

interface ApprovalStatusPresentation {
  color: "blue" | "green" | "gray" | "red" | "yellow";
  label: string;
  description: string;
}

function validHttpUrl(value: string | null): string | null {
  if (value === null) {
    return null;
  }
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.toString()
      : null;
  } catch {
    return null;
  }
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

function statusPresentation(
  request: ManagedApprovalRequest,
  t: ApprovalTranslator,
): ApprovalStatusPresentation {
  switch (request.status) {
    case "pending":
      return {
        color: "yellow",
        label: t("status.pending"),
        description: t("pendingDescription"),
      };
    case "allowed":
      return {
        color: "green",
        label: t("status.allowed"),
        description: t("completed.allowed"),
      };
    case "denied":
      return {
        color: "gray",
        label: t("status.denied"),
        description: t("completed.denied"),
      };
    case "blocked":
      return {
        color: "red",
        label: t("status.blocked"),
        description: t("completed.blocked"),
      };
    case "expired":
      return {
        color: "gray",
        label: t("status.expired"),
        description: t("completed.expired"),
      };
  }
}

function StateMessage({
  icon,
  title,
  description,
  actionLabel,
  onAction,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
}): React.ReactElement {
  return (
    <Container size="xs" py="xl">
      <Paper withBorder radius="lg" p="xl">
        <Stack align="center" gap="md" ta="center">
          <ThemeIcon variant="light" size="xl" radius="xl">
            {icon}
          </ThemeIcon>
          <Stack gap={rem(4)}>
            <Title order={1} size="h3">
              {title}
            </Title>
            <Text c="dimmed" size="sm">
              {description}
            </Text>
          </Stack>
          {actionLabel && onAction && (
            <Button
              variant="light"
              leftSection={<IconRefresh size={16} />}
              onClick={onAction}
            >
              {actionLabel}
            </Button>
          )}
        </Stack>
      </Paper>
    </Container>
  );
}

function DecisionButton({
  decision,
  currentDecision,
  label,
  description,
  color,
  icon,
  onDecision,
}: {
  decision: ExternalChannelApprovalDecision;
  currentDecision: ExternalChannelApprovalDecision | null;
  label: string;
  description: string;
  color: "blue" | "gray" | "red";
  icon: React.ReactNode;
  onDecision: (decision: ExternalChannelApprovalDecision) => void;
}): React.ReactElement {
  return (
    <Button
      variant={decision.startsWith("allow_") ? "filled" : "light"}
      color={color}
      leftSection={icon}
      loading={currentDecision === decision}
      disabled={currentDecision !== null}
      onClick={() => onDecision(decision)}
      h="auto"
      py="sm"
      styles={{
        inner: { justifyContent: "flex-start" },
        label: { whiteSpace: "normal", textAlign: "left" },
      }}
    >
      <Stack gap={rem(2)} align="flex-start">
        <Text component="span" fw={600} size="sm">
          {label}
        </Text>
        <Text component="span" fw={400} size="xs" opacity={0.8}>
          {description}
        </Text>
      </Stack>
    </Button>
  );
}

function ReadyApproval({
  state,
  onDecision,
}: {
  state: Extract<ExternalChannelApprovalState, { type: "READY" }>;
  onDecision: (decision: ExternalChannelApprovalDecision) => void;
}): React.ReactElement {
  const t = useTranslations("externalChannelApproval");
  const locale = useLocale();
  const status = statusPresentation(state.request, t);
  const originalUrl = validHttpUrl(state.request.original_url);
  const pending = state.request.status === "pending";

  return (
    <Container size="sm" py={{ base: "lg", sm: "xl" }}>
      <Paper withBorder radius="lg" p={{ base: "md", sm: "xl" }}>
        <Stack gap="lg">
          <Group justify="space-between" align="flex-start" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <ThemeIcon variant="light" size="lg" radius="md">
                <IconBrandSlack aria-hidden="true" size={20} />
              </ThemeIcon>
              <Stack gap={rem(2)}>
                <Title order={1} size="h3">
                  {t("title")}
                </Title>
                <Text c="dimmed" size="sm">
                  {t("subtitle")}
                </Text>
              </Stack>
            </Group>
            <Badge color={status.color} variant="light">
              {status.label}
            </Badge>
          </Group>

          <Alert
            color={pending ? "blue" : status.color}
            icon={
              pending ? (
                <IconLock size={16} />
              ) : (
                requestStatusIcon(state.request.status)
              )
            }
          >
            {status.description}
          </Alert>

          <Stack gap="sm">
            <DetailRow
              label={t("participant")}
              value={state.request.principal_label}
            />
            <DetailRow
              label={t("participantId")}
              value={state.request.principal_provider_user_id}
              copyValue={state.request.principal_provider_user_id}
            />
            <DetailRow
              label={t("source")}
              value={state.request.resource_label}
            />
            <DetailRow label={t("provider")} value={state.request.provider} />
            <DetailRow
              label={pending ? t("expiresAt") : t("decidedAt")}
              value={formatDateTime(
                pending
                  ? state.request.expires_at
                  : (state.request.decided_at ?? state.request.expires_at),
                locale,
              )}
            />
          </Stack>

          {state.request.source_text !== null && (
            <>
              <Divider />
              <Stack gap="xs">
                <Text size="xs" c="dimmed" fw={600} tt="uppercase">
                  {t("message")}
                </Text>
                <Paper
                  withBorder
                  radius="md"
                  p="sm"
                  bg="var(--mantine-color-default-hover)"
                >
                  <Text
                    size="sm"
                    style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                  >
                    {state.request.source_text}
                  </Text>
                </Paper>
              </Stack>
            </>
          )}

          {originalUrl !== null ? (
            <Anchor
              href={originalUrl}
              target="_blank"
              rel="noopener noreferrer"
              size="sm"
              fw={600}
            >
              <Group component="span" gap={rem(4)} wrap="nowrap">
                <IconExternalLink aria-hidden="true" size={16} />
                <span>{t("openOriginal")}</span>
              </Group>
            </Anchor>
          ) : (
            <Text size="sm" c="dimmed">
              {t("originalUnavailable")}
            </Text>
          )}

          {state.actionError !== null && (
            <Alert color="red" icon={<IconX size={16} />} role="alert">
              {state.actionError === "CONFLICT"
                ? t("errors.conflict")
                : t("errors.action")}
            </Alert>
          )}

          {pending && (
            <>
              <Divider />
              <Stack gap="sm">
                <Text fw={600}>{t("chooseAccess")}</Text>
                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
                  <DecisionButton
                    decision="allow_session"
                    currentDecision={state.submittingDecision}
                    label={t("actions.allowSession")}
                    description={t("actions.allowSessionDescription")}
                    color="blue"
                    icon={<IconUser size={16} />}
                    onDecision={onDecision}
                  />
                  <DecisionButton
                    decision="allow_agent"
                    currentDecision={state.submittingDecision}
                    label={t("actions.allowAgent")}
                    description={t("actions.allowAgentDescription")}
                    color="blue"
                    icon={<IconUsers size={16} />}
                    onDecision={onDecision}
                  />
                  <DecisionButton
                    decision="deny"
                    currentDecision={state.submittingDecision}
                    label={t("actions.deny")}
                    description={t("actions.denyDescription")}
                    color="gray"
                    icon={<IconX size={16} />}
                    onDecision={onDecision}
                  />
                  <DecisionButton
                    decision="block"
                    currentDecision={state.submittingDecision}
                    label={t("actions.block")}
                    description={t("actions.blockDescription")}
                    color="red"
                    icon={<IconBan size={16} />}
                    onDecision={onDecision}
                  />
                </SimpleGrid>
              </Stack>
            </>
          )}

          {!pending && state.request.decision_summary !== null && (
            <Text size="sm" c="dimmed">
              {t("decisionSummary", {
                summary: state.request.decision_summary,
              })}
            </Text>
          )}
        </Stack>
      </Paper>
    </Container>
  );
}

function DetailRow({
  label,
  value,
  copyValue,
}: {
  label: string;
  value: string;
  copyValue?: string;
}): React.ReactElement {
  const t = useTranslations("externalChannelApproval");
  return (
    <Group justify="space-between" align="flex-start" wrap="nowrap" gap="lg">
      <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
        {label}
      </Text>
      <Group gap="xs" justify="flex-end" wrap="nowrap" style={{ minWidth: 0 }}>
        <Text
          size="sm"
          fw={500}
          ta="right"
          style={{ minWidth: 0, overflowWrap: "anywhere" }}
        >
          {value}
        </Text>
        {typeof copyValue === "string" && (
          <CopyButton value={copyValue} timeout={1600}>
            {({ copied, copy }) => (
              <Button
                variant="subtle"
                color="gray"
                size="compact-xs"
                leftSection={
                  copied ? (
                    <IconCheck size={rem(13)} />
                  ) : (
                    <IconCopy size={rem(13)} />
                  )
                }
                onClick={copy}
                style={{ flexShrink: 0 }}
              >
                {copied ? t("copied") : t("copy")}
              </Button>
            )}
          </CopyButton>
        )}
      </Group>
    </Group>
  );
}

function requestStatusIcon(
  status: ManagedApprovalRequest["status"],
): React.ReactNode {
  return status === "allowed" ? <IconCheck size={16} /> : <IconX size={16} />;
}

export function ExternalChannelApproval({
  state,
  onDecision,
  onRetry,
}: ExternalChannelApprovalContainerOutput): React.ReactElement {
  const t = useTranslations("externalChannelApproval");

  switch (state.type) {
    case "LOADING":
      return (
        <Container size="xs" py="xl">
          <Stack align="center" gap="md" aria-live="polite">
            <Loader size="lg" />
            <Text c="dimmed">{t("loading")}</Text>
          </Stack>
        </Container>
      );
    case "NOT_FOUND":
      return (
        <StateMessage
          icon={<IconX size={22} />}
          title={t("notFoundTitle")}
          description={t("notFoundDescription")}
        />
      );
    case "UNAUTHORIZED":
      return (
        <StateMessage
          icon={<IconLock size={22} />}
          title={t("unauthorizedTitle")}
          description={t("unauthorizedDescription")}
        />
      );
    case "ERROR":
      return (
        <StateMessage
          icon={<IconX size={22} />}
          title={t("errorTitle")}
          description={t("errorDescription")}
          actionLabel={t("retry")}
          onAction={onRetry}
        />
      );
    case "READY":
      return <ReadyApproval state={state} onDecision={onDecision} />;
  }
}
