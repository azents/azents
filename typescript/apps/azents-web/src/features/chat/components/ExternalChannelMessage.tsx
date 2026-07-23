"use client";

import {
  Anchor,
  Badge,
  Box,
  Collapse,
  Group,
  Paper,
  rem,
  SimpleGrid,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  IconBrandSlack,
  IconChevronRight,
  IconExternalLink,
} from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";
import type { ExternalChannelMessagePresentation } from "../externalChannelMessage";

interface ExternalChannelMessageProps {
  source: ExternalChannelMessagePresentation;
  partial?: boolean;
}

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

function sourceStatusLabel(
  source: ExternalChannelMessagePresentation,
  t: ChatTranslator,
): string {
  if (source.lifecycle === "deleted") {
    return t("externalMessage.status.deleted");
  }
  if (source.revisionKind === "edit" || source.lifecycle === "edited") {
    return t("externalMessage.status.edited");
  }
  if (source.authorization === "authorized_invocation") {
    return t("externalMessage.status.invoked");
  }
  return t("externalMessage.status.context");
}

function statusColor(
  source: ExternalChannelMessagePresentation,
): "gray" | "blue" | "yellow" {
  if (source.lifecycle === "deleted") {
    return "gray";
  }
  if (source.authorization === "authorized_invocation") {
    return "blue";
  }
  return "yellow";
}

function formatTimestamp(value: string, locale: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function sourceMetadataRows(
  source: ExternalChannelMessagePresentation,
  t: ChatTranslator,
  locale: string,
): Array<{ label: string; value: string }> {
  const rows = [
    { label: t("externalMessage.provider"), value: source.provider },
    { label: t("externalMessage.resource"), value: source.resourceLabel },
    { label: t("externalMessage.sender"), value: source.senderDisplayName },
    { label: t("externalMessage.authorType"), value: source.authorType },
    {
      label: t("externalMessage.authorization"),
      value: source.authorization,
    },
    { label: t("externalMessage.lifecycle"), value: source.lifecycle },
    {
      label: t("externalMessage.timestamp"),
      value: formatTimestamp(source.providerTimestamp, locale),
    },
  ];
  if (source.revisionKind !== "original") {
    rows.push({
      label: t("externalMessage.revision"),
      value: source.revisionKind,
    });
  }
  if (source.correctionOfRevisionId !== null) {
    rows.push({
      label: t("externalMessage.corrects"),
      value: source.correctionOfRevisionId,
    });
  }
  return rows;
}

export function ExternalChannelMessage({
  source,
  partial = false,
}: ExternalChannelMessageProps): React.ReactElement {
  const t = useTranslations("chat");
  const locale = useLocale();
  const [opened, { toggle }] = useDisclosure(false);
  const sourceLabel = `${source.senderDisplayName} · ${source.resourceLabel}`;

  return (
    <Box mb="md" w="100%" style={{ minWidth: 0 }}>
      <Stack gap={rem(6)} maw={rem(760)}>
        <UnstyledButton
          type="button"
          onClick={toggle}
          aria-expanded={opened}
          aria-label={
            opened
              ? t("externalMessage.collapse", { source: sourceLabel })
              : t("externalMessage.expand", { source: sourceLabel })
          }
          py={rem(2)}
          style={{ borderRadius: "var(--mantine-radius-sm)" }}
        >
          <Group gap={rem(6)} c="dimmed" wrap="nowrap">
            <IconChevronRight
              aria-hidden="true"
              size={14}
              stroke={1.8}
              style={{
                flexShrink: 0,
                transform: opened ? "rotate(90deg)" : "none",
                transition: chatChevronTransition,
              }}
            />
            <IconBrandSlack
              aria-hidden="true"
              size={15}
              stroke={1.8}
              style={{ flexShrink: 0 }}
            />
            <Text size="xs" fw={600} tt="capitalize" style={{ flexShrink: 0 }}>
              {source.provider}
            </Text>
            <Text size="xs" c="dimmed" aria-hidden="true">
              ·
            </Text>
            <Text size="xs" fw={600} truncate style={{ minWidth: 0 }}>
              {source.senderDisplayName} ({source.authorType})
            </Text>
            <Text size="xs" c="dimmed" aria-hidden="true">
              ·
            </Text>
            <Text size="xs" truncate style={{ minWidth: 0 }}>
              {source.resourceLabel}
            </Text>
            <Badge
              size="xs"
              variant="light"
              color={statusColor(source)}
              style={{ flexShrink: 0 }}
            >
              {sourceStatusLabel(source, t)}
            </Badge>
            <Text
              size="xs"
              c="dimmed"
              visibleFrom="sm"
              style={{ flexShrink: 0 }}
            >
              {formatTimestamp(source.providerTimestamp, locale)}
            </Text>
          </Group>
        </UnstyledButton>

        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Paper
            withBorder
            radius="md"
            p="sm"
            bg="var(--mantine-color-body)"
            style={{ minWidth: 0, overflow: "hidden" }}
          >
            <Stack gap="md">
              <Box style={{ overflowWrap: "anywhere" }}>
                <MarkdownContent>{source.body}</MarkdownContent>
                {partial && (
                  <Text component="span" fw={700} size="sm">
                    |
                  </Text>
                )}
              </Box>

              <SimpleGrid
                component="dl"
                cols={{ base: 1, sm: 2 }}
                spacing="sm"
                m={0}
              >
                {sourceMetadataRows(source, t, locale).map((row) => (
                  <Stack key={row.label} gap={rem(2)}>
                    <Text component="dt" size="xs" c="dimmed" fw={600}>
                      {row.label}
                    </Text>
                    <Text
                      component="dd"
                      m={0}
                      size="xs"
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {row.value}
                    </Text>
                  </Stack>
                ))}
              </SimpleGrid>

              {source.originalUrl !== null ? (
                <Anchor
                  href={source.originalUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  size="xs"
                  fw={600}
                  aria-label={t("externalMessage.openOriginalAccessible", {
                    resource: source.resourceLabel,
                  })}
                >
                  <Group component="span" gap={rem(4)} wrap="nowrap">
                    <IconExternalLink aria-hidden="true" size={14} />
                    <span>{t("externalMessage.openOriginal")}</span>
                  </Group>
                </Anchor>
              ) : (
                <Text size="xs" c="dimmed">
                  {t("externalMessage.originalUnavailable")}
                </Text>
              )}
            </Stack>
          </Paper>
        </Collapse>
      </Stack>
    </Box>
  );
}
