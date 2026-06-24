"use client";

/** Agent session context inspector view. */
import {
  Accordion,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Code,
  CopyButton,
  Divider,
  Group,
  Paper,
  Progress,
  rem,
  ScrollArea,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconArrowLeft,
  IconChevronRight,
  IconCopy,
  IconListDetails,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import type {
  SessionContextResponse,
  SessionContextSystemPromptFragmentResponse,
} from "@azents/public-client";

interface SessionContextViewProps {
  context: SessionContextResponse;
  systemPromptHref: string;
  rawEventsHref: string;
}

interface SessionSystemPromptViewProps {
  context: SessionContextResponse;
}

interface SessionRawEventsViewProps {
  context: SessionContextResponse;
}

const BREAKDOWN_COLORS: Record<string, string> = {
  system: "violet",
  user: "green",
  assistant: "blue",
  tool: "orange",
  other: "gray",
};

const PROMPT_SOURCE_COLORS: Record<string, string> = {
  agent: "violet",
  toolkit: "blue",
  turn_injected: "orange",
  final: "teal",
};

function formatNumber(value: unknown): string {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

function formatCost(value?: number | null): string {
  if (value === null || typeof value !== "number") {
    return "—";
  }
  return `$${value.toFixed(6)}`;
}

function getUsageNumber(
  usage: Record<string, unknown> | null,
  key: string,
): number | null {
  if (usage === null) {
    return null;
  }
  const value = usage[key];
  return typeof value === "number" ? value : null;
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function promptDetailId(
  group: "agent" | "toolkit" | "injected" | "final",
  id: string,
): string {
  return `${group}:${id}`;
}

function promptLength(
  prompt: SessionContextSystemPromptFragmentResponse | null,
): string {
  if (!prompt) {
    return "—";
  }
  return prompt.length.toLocaleString();
}

function totalPromptLength(
  prompts: SessionContextSystemPromptFragmentResponse[],
): string {
  return prompts
    .reduce((total, prompt) => total + prompt.length, 0)
    .toLocaleString();
}

function sourceColor(source: string): string {
  return PROMPT_SOURCE_COLORS[source] ?? "gray";
}

function metadataEntries(
  metadata: Record<string, string>,
): Array<[string, string]> {
  return Object.entries(metadata).filter((entry) => entry[1].trim().length > 0);
}

export function SessionContextView({
  context,
  systemPromptHref,
  rawEventsHref,
}: SessionContextViewProps): React.ReactElement {
  const t = useTranslations("chat.context");
  if (context.session.id === null) {
    return (
      <Alert
        icon={<IconAlertCircle size={rem(16)} />}
        color="gray"
        variant="light"
      >
        {t("empty")}
      </Alert>
    );
  }

  const usage = context.usage ?? null;
  const totalTokens = getUsageNumber(usage, "total_tokens");
  const promptTokens = getUsageNumber(usage, "prompt_tokens");
  const completionTokens = getUsageNumber(usage, "completion_tokens");
  const reasoningTokens = getUsageNumber(usage, "reasoning_tokens");
  const cachedTokens = getUsageNumber(usage, "cached_tokens");
  const cacheCreationTokens = getUsageNumber(usage, "cache_creation_tokens");
  return (
    <Stack gap="md">
      <SimpleGrid cols={{ base: 2, md: 4 }} spacing="sm">
        <StatCard label={t("totalTokens")} value={formatNumber(totalTokens)} />
        <StatCard label={t("inputTokens")} value={formatNumber(promptTokens)} />
        <StatCard
          label={t("outputTokens")}
          value={formatNumber(completionTokens)}
        />
        <StatCard
          label={t("totalCost")}
          value={formatCost(context.stats.total_cost_usd)}
        />
        <StatCard
          label={t("reasoning")}
          value={formatNumber(reasoningTokens)}
        />
        <StatCard label={t("cacheRead")} value={formatNumber(cachedTokens)} />
        <StatCard
          label={t("cacheWrite")}
          value={formatNumber(cacheCreationTokens)}
        />
        <StatCard
          label={t("rawEvents")}
          value={context.stats.total_events.toLocaleString()}
        />
      </SimpleGrid>

      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Box>
              <Text fw={600}>{t("contextBreakdown")}</Text>
              <Text size="xs" c="dimmed">
                {t("breakdownDescription")}
              </Text>
            </Box>
            {promptTokens !== null && (
              <Badge variant="light">
                {t("inputTokensBadge", {
                  count: promptTokens.toLocaleString(),
                })}
              </Badge>
            )}
          </Group>
          {context.breakdown.length > 0 ? (
            <>
              <Progress.Root size="xl" radius="xl">
                {context.breakdown.map((segment) => (
                  <Progress.Section
                    key={segment.key}
                    value={segment.percent}
                    color={BREAKDOWN_COLORS[segment.key] ?? "gray"}
                  />
                ))}
              </Progress.Root>
              <Group gap="xs" wrap="wrap">
                {context.breakdown.map((segment) => (
                  <Badge
                    key={segment.key}
                    color={BREAKDOWN_COLORS[segment.key] ?? "gray"}
                    variant="light"
                  >
                    {t(`breakdown.${segment.key}`)}:{" "}
                    {t("characters", {
                      count: segment.tokens.toLocaleString(),
                    })}{" "}
                    ({segment.percent}%)
                  </Badge>
                ))}
              </Group>
            </>
          ) : (
            <Text size="sm" c="dimmed">
              {t("noUsage")}
            </Text>
          )}
        </Stack>
      </Paper>

      <SystemPromptLinkCard
        context={context}
        systemPromptHref={systemPromptHref}
      />

      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600}>{t("eventStats")}</Text>
            <Text size="xs" c="dimmed">
              {t("session", { id: context.session.id })}
            </Text>
          </Group>
          <SimpleGrid cols={{ base: 2, md: 4 }} spacing="xs">
            <StatCard
              label={t("user")}
              value={context.stats.user_messages.toLocaleString()}
              compact
            />
            <StatCard
              label={t("assistant")}
              value={context.stats.assistant_messages.toLocaleString()}
              compact
            />
            <StatCard
              label={t("reasoning")}
              value={context.stats.reasoning_events.toLocaleString()}
              compact
            />
            <StatCard
              label={t("toolCalls")}
              value={context.stats.tool_calls.toLocaleString()}
              compact
            />
            <StatCard
              label={t("toolResults")}
              value={context.stats.tool_results.toLocaleString()}
              compact
            />
            <StatCard
              label={t("turns")}
              value={context.stats.turn_markers.toLocaleString()}
              compact
            />
          </SimpleGrid>
        </Stack>
      </Paper>

      <RawEventsLinkCard context={context} rawEventsHref={rawEventsHref} />
    </Stack>
  );
}

export function SessionSystemPromptView({
  context,
}: SessionSystemPromptViewProps): React.ReactElement {
  const t = useTranslations("chat.context");
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);
  const systemPrompt = context.system_prompt ?? null;
  const agentPrompt = systemPrompt?.agent_prompt ?? null;
  const finalPrompt = systemPrompt?.final_prompt ?? null;
  const promptDetails = [
    ...(agentPrompt
      ? [
          {
            id: promptDetailId("agent", agentPrompt.id),
            prompt: agentPrompt,
          },
        ]
      : []),
    ...(systemPrompt?.toolkit_prompts.map((prompt) => ({
      id: promptDetailId("toolkit", prompt.id),
      prompt,
    })) ?? []),
    ...(systemPrompt?.injected_prompts.map((prompt) => ({
      id: promptDetailId("injected", prompt.id),
      prompt,
    })) ?? []),
    ...(finalPrompt
      ? [
          {
            id: promptDetailId("final", finalPrompt.id),
            prompt: finalPrompt,
          },
        ]
      : []),
  ];
  const selectedPrompt =
    promptDetails.find((detail) => detail.id === selectedPromptId)?.prompt ??
    null;

  if (context.session.id === null) {
    return (
      <Alert
        icon={<IconAlertCircle size={rem(16)} />}
        color="gray"
        variant="light"
      >
        {t("empty")}
      </Alert>
    );
  }

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Box>
            <Text fw={600}>{t("systemPrompt.title")}</Text>
            <Text size="xs" c="dimmed">
              {t("systemPrompt.description")}
            </Text>
          </Box>
          {systemPrompt !== null && (
            <Badge variant="light" color="violet">
              {t("systemPrompt.fragmentsBadge", {
                count: promptDetails.length.toLocaleString(),
              })}
            </Badge>
          )}
        </Group>

        {systemPrompt === null ? (
          <Alert color="gray" variant="light">
            {t("systemPrompt.empty")}
          </Alert>
        ) : selectedPrompt !== null ? (
          <PromptDetail
            prompt={selectedPrompt}
            onBack={() => setSelectedPromptId(null)}
          />
        ) : (
          <Stack gap="md">
            <SimpleGrid cols={{ base: 1, md: 3 }} spacing="sm">
              <PromptSummaryCard
                label={t("systemPrompt.agentPrompt")}
                description={t("systemPrompt.agentPromptDescription")}
                count={promptLength(agentPrompt)}
                preview={agentPrompt?.preview ?? null}
                disabled={agentPrompt === null}
                onOpen={
                  agentPrompt
                    ? () =>
                        setSelectedPromptId(
                          promptDetailId("agent", agentPrompt.id),
                        )
                    : null
                }
              />
              <PromptSummaryCard
                label={t("systemPrompt.toolkitPrompts")}
                description={t("systemPrompt.toolkitPromptsDescription", {
                  count: systemPrompt.toolkit_prompts.length.toLocaleString(),
                })}
                count={totalPromptLength(systemPrompt.toolkit_prompts)}
                preview={systemPrompt.toolkit_prompts[0]?.preview ?? null}
                disabled={systemPrompt.toolkit_prompts.length === 0}
                onOpen={null}
              />
              <PromptSummaryCard
                label={t("systemPrompt.finalPrompt")}
                description={t("systemPrompt.finalPromptDescription")}
                count={promptLength(finalPrompt)}
                preview={finalPrompt?.preview ?? null}
                disabled={finalPrompt === null}
                onOpen={
                  finalPrompt
                    ? () =>
                        setSelectedPromptId(
                          promptDetailId("final", finalPrompt.id),
                        )
                    : null
                }
              />
            </SimpleGrid>

            <Divider />

            <Stack gap="sm">
              <Group justify="space-between">
                <Box>
                  <Text fw={600}>{t("systemPrompt.toolkitPrompts")}</Text>
                  <Text size="xs" c="dimmed">
                    {t("systemPrompt.toolkitListDescription")}
                  </Text>
                </Box>
                <Badge variant="light" color="blue">
                  {systemPrompt.toolkit_prompts.length.toLocaleString()}
                </Badge>
              </Group>
              {systemPrompt.toolkit_prompts.length > 0 ? (
                <Stack gap="xs">
                  {systemPrompt.toolkit_prompts.map((prompt) => (
                    <PromptListItem
                      key={prompt.id}
                      prompt={prompt}
                      onOpen={() =>
                        setSelectedPromptId(
                          promptDetailId("toolkit", prompt.id),
                        )
                      }
                    />
                  ))}
                </Stack>
              ) : (
                <Text size="sm" c="dimmed">
                  {t("systemPrompt.noToolkitPrompts")}
                </Text>
              )}
            </Stack>

            {systemPrompt.injected_prompts.length > 0 && (
              <Stack gap="sm">
                <Divider />
                <Group justify="space-between">
                  <Box>
                    <Text fw={600}>{t("systemPrompt.debugEvents")}</Text>
                    <Text size="xs" c="dimmed">
                      {t("systemPrompt.debugEventsDescription")}
                    </Text>
                  </Box>
                  <Badge variant="light" color="orange">
                    {systemPrompt.injected_prompts.length.toLocaleString()}
                  </Badge>
                </Group>
                <Stack gap="xs">
                  {systemPrompt.injected_prompts.map((prompt) => (
                    <PromptListItem
                      key={prompt.id}
                      prompt={prompt}
                      onOpen={() =>
                        setSelectedPromptId(
                          promptDetailId("injected", prompt.id),
                        )
                      }
                    />
                  ))}
                </Stack>
              </Stack>
            )}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

export function SessionRawEventsView({
  context,
}: SessionRawEventsViewProps): React.ReactElement {
  const t = useTranslations("chat.context");
  const [openedEventId, setOpenedEventId] = useState<string | null>(null);

  if (context.session.id === null) {
    return (
      <Alert
        icon={<IconAlertCircle size={rem(16)} />}
        color="gray"
        variant="light"
      >
        {t("empty")}
      </Alert>
    );
  }

  return (
    <Paper withBorder radius="md" p="md">
      <Stack gap="md">
        <Group justify="space-between" align="flex-start">
          <Box>
            <Text fw={600}>{t("rawEventsPage.title")}</Text>
            <Text size="xs" c="dimmed">
              {t("rawEventsPage.description")}
            </Text>
          </Box>
          <Badge variant="light" color="gray">
            {t("rawEventsPage.eventsBadge", {
              count: context.raw_events.length.toLocaleString(),
            })}
          </Badge>
        </Group>
        <Accordion
          variant="separated"
          radius="md"
          value={openedEventId}
          onChange={setOpenedEventId}
          disableChevronRotation
        >
          {context.raw_events.map((event) => (
            <Accordion.Item key={event.id} value={event.id}>
              <Accordion.Control
                chevron={
                  <IconChevronRight
                    size={rem(16)}
                    style={{
                      transform:
                        openedEventId === event.id
                          ? "rotate(90deg)"
                          : "rotate(0deg)",
                      transition: "transform 120ms ease",
                    }}
                  />
                }
              >
                <Group gap="xs" wrap="nowrap">
                  <Badge size="sm" variant="light">
                    {event.kind}
                  </Badge>
                  <Text size="sm" c="dimmed" truncate>
                    {new Date(event.created_at).toLocaleString()}
                  </Text>
                  {event.model && (
                    <Text size="xs" c="dimmed" truncate>
                      {event.model}
                    </Text>
                  )}
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <ScrollArea.Autosize mah={rem(560)}>
                  <Code block style={{ fontSize: rem(12) }}>
                    {stringifyJson(event)}
                  </Code>
                </ScrollArea.Autosize>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      </Stack>
    </Paper>
  );
}

function RawEventsLinkCard({
  context,
  rawEventsHref,
}: {
  context: SessionContextResponse;
  rawEventsHref: string;
}): React.ReactElement {
  const t = useTranslations("chat.context.rawEventsPage");

  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" align="center">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <ThemeIconLike color="gray" />
          <Box style={{ minWidth: 0 }}>
            <Text fw={600}>{t("title")}</Text>
            <Text size="xs" c="dimmed" lineClamp={2}>
              {t("linkDescription")}
            </Text>
          </Box>
        </Group>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          <Badge variant="light" color="gray">
            {t("eventsBadge", {
              count: context.raw_events.length.toLocaleString(),
            })}
          </Badge>
          <Button
            component={Link}
            href={rawEventsHref}
            variant="light"
            rightSection={<IconChevronRight size={rem(14)} />}
          >
            {t("openPage")}
          </Button>
        </Group>
      </Group>
    </Card>
  );
}

function SystemPromptLinkCard({
  context,
  systemPromptHref,
}: {
  context: SessionContextResponse;
  systemPromptHref: string;
}): React.ReactElement {
  const t = useTranslations("chat.context.systemPrompt");
  const systemPrompt = context.system_prompt ?? null;
  const fragmentCount = systemPrompt
    ? [
        systemPrompt.agent_prompt,
        ...systemPrompt.toolkit_prompts,
        ...systemPrompt.injected_prompts,
        systemPrompt.final_prompt,
      ].filter(Boolean).length
    : 0;

  return (
    <Card withBorder radius="md" p="md">
      <Group justify="space-between" align="center">
        <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
          <ThemeIconLike color="violet" />
          <Box style={{ minWidth: 0 }}>
            <Text fw={600}>{t("title")}</Text>
            <Text size="xs" c="dimmed" lineClamp={2}>
              {t("linkDescription")}
            </Text>
          </Box>
        </Group>
        <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
          {systemPrompt !== null && (
            <Badge variant="light" color="violet">
              {t("fragmentsBadge", {
                count: fragmentCount.toLocaleString(),
              })}
            </Badge>
          )}
          <Button
            component={Link}
            href={systemPromptHref}
            variant="light"
            rightSection={<IconChevronRight size={rem(14)} />}
          >
            {t("openPage")}
          </Button>
        </Group>
      </Group>
    </Card>
  );
}

function ThemeIconLike({ color }: { color: string }): React.ReactElement {
  return (
    <Box
      c={color}
      style={{
        alignItems: "center",
        backgroundColor: `var(--mantine-color-${color}-light)`,
        borderRadius: "var(--mantine-radius-md)",
        display: "flex",
        flexShrink: 0,
        height: rem(40),
        justifyContent: "center",
        width: rem(40),
      }}
    >
      <IconListDetails size={rem(20)} />
    </Box>
  );
}

function StatCard({
  label,
  value,
  compact,
}: {
  label: string;
  value: string;
  compact?: boolean;
}): React.ReactElement {
  return (
    <Paper withBorder radius="md" p={compact ? "xs" : "sm"}>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={600} size={compact ? "sm" : "lg"}>
        {value}
      </Text>
    </Paper>
  );
}

function PromptSummaryCard({
  label,
  description,
  count,
  preview,
  disabled,
  onOpen,
}: {
  label: string;
  description: string;
  count: string;
  preview: string | null;
  disabled: boolean;
  onOpen: (() => void) | null;
}): React.ReactElement {
  const t = useTranslations("chat.context.systemPrompt");
  return (
    <Paper withBorder radius="md" p="sm">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Text fw={600} size="sm">
              {label}
            </Text>
            <Text size="xs" c="dimmed">
              {description}
            </Text>
          </Box>
          <Badge variant="light" style={{ flexShrink: 0 }}>
            {t("characters", { count })}
          </Badge>
        </Group>
        {preview ? (
          <Text size="sm" lineClamp={3}>
            {preview}
          </Text>
        ) : (
          <Text size="sm" c="dimmed" lineClamp={3}>
            {t("emptyPrompt")}
          </Text>
        )}
        {onOpen && (
          <Button
            variant="light"
            size="xs"
            rightSection={<IconChevronRight size={rem(14)} />}
            disabled={disabled}
            onClick={onOpen}
          >
            {t("viewDetails")}
          </Button>
        )}
      </Stack>
    </Paper>
  );
}

function PromptListItem({
  prompt,
  onOpen,
}: {
  prompt: SessionContextSystemPromptFragmentResponse;
  onOpen: () => void;
}): React.ReactElement {
  const t = useTranslations("chat.context.systemPrompt");
  const entries = metadataEntries(prompt.metadata);
  return (
    <Paper withBorder radius="md" p="sm">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={600} size="sm">
                {prompt.label}
              </Text>
              <Badge
                size="sm"
                variant="light"
                color={sourceColor(prompt.source)}
              >
                {t(`source.${prompt.source}`)}
              </Badge>
            </Group>
            {entries.length > 0 && (
              <Group gap="xs" mt="xs" wrap="wrap">
                {entries.map(([key, value]) => (
                  <Badge key={key} size="xs" variant="outline" color="gray">
                    {key}: {value}
                  </Badge>
                ))}
              </Group>
            )}
          </Box>
          <Badge variant="light" style={{ flexShrink: 0 }}>
            {t("characters", { count: prompt.length.toLocaleString() })}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed" lineClamp={2}>
          {prompt.preview}
        </Text>
        <Button
          variant="subtle"
          size="xs"
          rightSection={<IconChevronRight size={rem(14)} />}
          onClick={onOpen}
        >
          {t("viewDetails")}
        </Button>
      </Stack>
    </Paper>
  );
}

function PromptDetail({
  prompt,
  onBack,
}: {
  prompt: SessionContextSystemPromptFragmentResponse;
  onBack: () => void;
}): React.ReactElement {
  const t = useTranslations("chat.context.systemPrompt");
  const entries = metadataEntries(prompt.metadata);
  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Button
          variant="subtle"
          size="xs"
          leftSection={<IconArrowLeft size={rem(14)} />}
          onClick={onBack}
        >
          {t("back")}
        </Button>
        <CopyButton value={prompt.content}>
          {({ copied, copy }): React.ReactElement => (
            <Button
              variant="light"
              size="xs"
              leftSection={<IconCopy size={rem(14)} />}
              onClick={copy}
            >
              {copied ? t("copied") : t("copy")}
            </Button>
          )}
        </CopyButton>
      </Group>
      <Stack gap="xs">
        <Group gap="xs" wrap="wrap">
          <Text fw={600}>{prompt.label}</Text>
          <Badge variant="light" color={sourceColor(prompt.source)}>
            {t(`source.${prompt.source}`)}
          </Badge>
          <Badge variant="light" style={{ flexShrink: 0 }}>
            {t("characters", { count: prompt.length.toLocaleString() })}
          </Badge>
        </Group>
        {entries.length > 0 && (
          <Group gap="xs" wrap="wrap">
            {entries.map(([key, value]) => (
              <Badge key={key} size="sm" variant="outline" color="gray">
                {key}: {value}
              </Badge>
            ))}
          </Group>
        )}
      </Stack>
      <ScrollArea.Autosize mah={rem(560)}>
        <Code
          block
          style={{
            fontSize: rem(12),
            whiteSpace: "pre-wrap",
          }}
        >
          {prompt.content}
        </Code>
      </ScrollArea.Autosize>
    </Stack>
  );
}
