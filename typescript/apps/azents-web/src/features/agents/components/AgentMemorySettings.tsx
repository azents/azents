"use client";

/** Agent Memory settings UI. */

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Group,
  Loader,
  Modal,
  Paper,
  rem,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import {
  IconArrowLeft,
  IconChevronRight,
  IconEdit,
  IconExternalLink,
  IconPlus,
  IconSearch,
  IconTrash,
} from "@tabler/icons-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { MarkdownContent } from "@/features/chat/components/MarkdownContent";
import type {
  ConsolidatedMemoryState,
  HistoricalMemoryListState,
  HistoricalMemoryScopeValue,
  HistoricalMemoryView,
  MemoryDraft,
  MemoryKindValue,
  MemoryPaginationState,
  SavedMemoryListState,
  SavedMemoryScopeValue,
} from "../containers/useAgentMemorySettingsContainer";
import type {
  AgentResponse,
  HistoricalMemoryResponse,
  MemoryResponse,
} from "@azents/public-client";
import type { RefCallback } from "react";

type DraftState =
  | { type: "create"; draft: MemoryDraft }
  | { type: "edit"; memoryId: string; draft: MemoryDraft }
  | null;

interface AgentMemorySettingsProps {
  handle: string;
  agent: AgentResponse;
  memoryEnabled: boolean;
  kind: MemoryKindValue;
  savedScope: SavedMemoryScopeValue;
  historicalScope: HistoricalMemoryScopeValue;
  savedQuery: string;
  historicalQuery: string;
  savedListState: SavedMemoryListState;
  historicalListState: HistoricalMemoryListState;
  draftState: DraftState;
  actionError: string | null;
  saving: boolean;
  deletingId: string | null;
  togglingMemory: boolean;
  historicalView: HistoricalMemoryView;
  consolidatedState: ConsolidatedMemoryState;
  paginationState: MemoryPaginationState;
  scrollRootRef: RefCallback<HTMLDivElement>;
  scrollEndRef: RefCallback<HTMLDivElement>;
  onHistoricalViewChange: (view: HistoricalMemoryView) => void;
  onRetryNextPage: () => void;
  onKindChange: (kind: MemoryKindValue) => void;
  onSavedScopeChange: (scope: SavedMemoryScopeValue) => void;
  onHistoricalScopeChange: (scope: HistoricalMemoryScopeValue) => void;
  onSavedQueryChange: (query: string) => void;
  onHistoricalQueryChange: (query: string) => void;
  onMemoryEnabledChange: (enabled: boolean) => void;
  onStartCreate: () => void;
  onStartEdit: (memory: MemoryResponse) => void;
  onCancelDraft: () => void;
  onDraftChange: (draft: MemoryDraft) => void;
  onSaveDraft: () => void;
  onDeleteMemory: (memory: MemoryResponse) => void;
}

function toMemoryKindValue(value: string): MemoryKindValue {
  return value === "historical" ? "historical" : "saved";
}

function toSavedMemoryScopeValue(value: string): SavedMemoryScopeValue {
  return value === "user" ? "user" : "agent";
}

function toHistoricalMemoryScopeValue(
  value: string,
): HistoricalMemoryScopeValue {
  return value === "user" ? "user" : "team";
}

function MemoryCard({
  memory,
  deleting,
  onEdit,
  onDelete,
}: {
  memory: MemoryResponse;
  deleting: boolean;
  onEdit: (memory: MemoryResponse) => void;
  onDelete: (memory: MemoryResponse) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  return (
    <Card withBorder radius="lg" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Group gap="xs" wrap="nowrap">
              <Text fw={700} truncate>
                {memory.name}
              </Text>
              <Badge variant="light" color="gray" size="sm">
                {memory.type}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed" lineClamp={2}>
              {memory.description}
            </Text>
          </Box>
          <Group gap="xs" wrap="nowrap">
            <ActionIcon
              variant="subtle"
              aria-label={t("edit")}
              onClick={() => onEdit(memory)}
            >
              <IconEdit size={rem(16)} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={t("delete")}
              loading={deleting}
              onClick={() => onDelete(memory)}
            >
              <IconTrash size={rem(16)} />
            </ActionIcon>
          </Group>
        </Group>
        <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-body)">
          <Text size="sm" style={{ whiteSpace: "pre-wrap" }} lineClamp={4}>
            {memory.content}
          </Text>
        </Paper>
      </Stack>
    </Card>
  );
}

function SavedMemoryList({
  state,
  deletingId,
  onEdit,
  onDelete,
}: {
  state: SavedMemoryListState;
  deletingId: string | null;
  onEdit: (memory: MemoryResponse) => void;
  onDelete: (memory: MemoryResponse) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      );
    case "ERROR":
      return <Alert color="red">{state.message}</Alert>;
    case "LOADED":
      if (state.memories.length === 0) {
        return (
          <Paper withBorder radius="lg" p="xl">
            <Stack gap="xs" align="center">
              <Text fw={700}>{t("savedEmptyTitle")}</Text>
              <Text size="sm" c="dimmed" ta="center">
                {t("savedEmptyDescription")}
              </Text>
            </Stack>
          </Paper>
        );
      }
      return (
        <Stack gap="sm">
          {state.memories.map((memory) => (
            <MemoryCard
              key={memory.id}
              memory={memory}
              deleting={deletingId === memory.id}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}
        </Stack>
      );
  }
}

function HistoricalMemoryCard({
  memory,
}: {
  memory: HistoricalMemoryResponse;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  const format = useFormatter();
  const sourceTitle = memory.source_title ?? t("untitledConversation");
  return (
    <Card withBorder radius="lg" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start" gap="md">
          <Stack gap={4} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={700} lineClamp={2}>
                {sourceTitle}
              </Text>
              <Badge variant="light" color="gray" size="sm">
                {memory.scope === "team"
                  ? t("teamScopeBadge")
                  : t("personalScopeBadge")}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed">
              {t("sourceActivityDate", {
                date: format.dateTime(
                  new Date(memory.source_activity_through),
                  {
                    dateStyle: "medium",
                  },
                ),
              })}
            </Text>
          </Stack>
          <Button
            component={Link}
            href={memory.source_path}
            variant="subtle"
            size="compact-sm"
            rightSection={<IconExternalLink size={rem(14)} />}
            aria-label={t("openConversationLabel", { title: sourceTitle })}
          >
            {t("openConversation")}
          </Button>
        </Group>
        <Paper withBorder radius="md" p="sm" bg="var(--mantine-color-body)">
          <Text size="sm" style={{ whiteSpace: "pre-wrap" }} lineClamp={6}>
            {memory.summary}
          </Text>
        </Paper>
        <Text size="xs" c="dimmed">
          {t("preparedDate", {
            date: format.dateTime(new Date(memory.prepared_at), {
              dateStyle: "medium",
            }),
          })}
        </Text>
      </Stack>
    </Card>
  );
}

function HistoricalMemoryList({
  state,
  scope,
}: {
  state: HistoricalMemoryListState;
  scope: HistoricalMemoryScopeValue;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      );
    case "ERROR":
      return <Alert color="red">{state.message}</Alert>;
    case "LOADED":
      if (state.memories.length === 0) {
        return (
          <Paper withBorder radius="lg" p="xl">
            <Stack gap="xs" align="center">
              <Text fw={700}>{t("historicalEmptyTitle")}</Text>
              <Text size="sm" c="dimmed" ta="center">
                {t("historicalEmptyDescription")}
              </Text>
            </Stack>
          </Paper>
        );
      }
      return (
        <Stack gap="sm">
          <Group justify="space-between" align="center">
            <Text fw={700} size="sm">
              {scope === "team"
                ? t("teamConversations")
                : t("personalConversations")}
            </Text>
            <Text size="xs" c="dimmed">
              {t("historicalCount", { count: state.memories.length })}
            </Text>
          </Group>
          {state.memories.map((memory) => (
            <HistoricalMemoryCard
              key={memory.source_session_id}
              memory={memory}
            />
          ))}
        </Stack>
      );
  }
}

function ConsolidatedMemory({
  state,
}: {
  state: ConsolidatedMemoryState;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  const format = useFormatter();
  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      );
    case "ERROR":
      return <Alert color="red">{state.message}</Alert>;
    case "LOADED":
      return (
        <Paper withBorder radius="lg" p="md">
          <Stack gap="sm">
            <Text fw={700}>{t("integratedTitle")}</Text>
            {state.markdown === null ? (
              <Text size="sm" c="dimmed">
                {t("integratedEmpty")}
              </Text>
            ) : (
              <Box style={{ overflowWrap: "anywhere", minWidth: 0 }}>
                <MarkdownContent>{state.markdown}</MarkdownContent>
              </Box>
            )}
            {state.publishedAt !== null && (
              <Text size="xs" c="dimmed">
                {t("integratedDate", {
                  date: format.dateTime(new Date(state.publishedAt), {
                    dateStyle: "medium",
                  }),
                })}
              </Text>
            )}
          </Stack>
        </Paper>
      );
  }
}

function PaginationStatus({
  state,
  endRef,
  onRetry,
}: {
  state: MemoryPaginationState;
  endRef: RefCallback<HTMLDivElement>;
  onRetry: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  return (
    <Box
      ref={endRef}
      data-testid="memory-scroll-end"
      py="sm"
      style={{ minHeight: rem(24) }}
    >
      {state.type === "LOADING" && (
        <Center role="status" aria-label={t("loadingMore")}>
          <Loader size="sm" />
        </Center>
      )}
      {state.type === "ERROR" && (
        <Alert color="red">
          <Stack gap="xs">
            <Text size="sm">{state.message}</Text>
            <Button variant="subtle" onClick={onRetry} size="compact-sm">
              {t("retry")}
            </Button>
          </Stack>
        </Alert>
      )}
    </Box>
  );
}

function MemoryDraftModal({
  draftState,
  saving,
  onCancel,
  onDraftChange,
  onSave,
}: {
  draftState: DraftState;
  saving: boolean;
  onCancel: () => void;
  onDraftChange: (draft: MemoryDraft) => void;
  onSave: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");
  const draft = draftState?.draft ?? null;
  const opened = draft !== null;
  const disabled =
    draft === null ||
    draft.type.trim() === "" ||
    draft.name.trim() === "" ||
    draft.description.trim() === "" ||
    draft.content.trim() === "";

  return (
    <Modal
      opened={opened}
      onClose={onCancel}
      title={draftState?.type === "edit" ? t("editTitle") : t("createTitle")}
      size="lg"
    >
      {draft && (
        <Stack gap="md">
          <TextInput
            label={t("typeLabel")}
            value={draft.type}
            onChange={(event) =>
              onDraftChange({ ...draft, type: event.currentTarget.value })
            }
          />
          <TextInput
            label={t("nameLabel")}
            value={draft.name}
            onChange={(event) =>
              onDraftChange({ ...draft, name: event.currentTarget.value })
            }
          />
          <TextInput
            label={t("descriptionLabel")}
            value={draft.description}
            onChange={(event) =>
              onDraftChange({
                ...draft,
                description: event.currentTarget.value,
              })
            }
          />
          <Textarea
            label={t("contentLabel")}
            value={draft.content}
            autosize
            minRows={8}
            onChange={(event) =>
              onDraftChange({ ...draft, content: event.currentTarget.value })
            }
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={onCancel}>
              {t("cancel")}
            </Button>
            <Button loading={saving} disabled={disabled} onClick={onSave}>
              {t("save")}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}

export function AgentMemorySettings({
  memoryEnabled,
  kind,
  savedScope,
  historicalScope,
  savedQuery,
  historicalQuery,
  savedListState,
  historicalListState,
  draftState,
  actionError,
  saving,
  deletingId,
  togglingMemory,
  historicalView,
  consolidatedState,
  paginationState,
  scrollRootRef,
  scrollEndRef,
  onHistoricalViewChange,
  onRetryNextPage,
  onKindChange,
  onSavedScopeChange,
  onHistoricalScopeChange,
  onSavedQueryChange,
  onHistoricalQueryChange,
  onMemoryEnabledChange,
  onStartCreate,
  onStartEdit,
  onCancelDraft,
  onDraftChange,
  onSaveDraft,
  onDeleteMemory,
}: AgentMemorySettingsProps): React.ReactElement {
  const t = useTranslations("workspace.agents.memorySettings");

  return (
    <Box
      ref={scrollRootRef}
      data-testid="memory-scroll-root"
      style={{ flex: 1, overflow: "auto", minHeight: 0 }}
    >
      <Stack gap="lg" p="md" maw={rem(960)} mx="auto" w="100%">
        <Paper withBorder radius="lg" p="lg">
          <Stack gap="sm">
            <Group justify="space-between" align="center" gap="md">
              <Text fw={700} size="xl">
                {t("title")}
              </Text>
              <Switch
                checked={memoryEnabled}
                disabled={togglingMemory}
                label={t("enabledLabel")}
                onChange={(event) =>
                  onMemoryEnabledChange(event.currentTarget.checked)
                }
              />
            </Group>
            <Text size="sm" c="dimmed" data-testid="memory-description">
              {t("description")}
            </Text>
          </Stack>
        </Paper>

        <SegmentedControl
          value={kind}
          onChange={(value) => onKindChange(toMemoryKindValue(value))}
          data={[
            { label: t("savedKind"), value: "saved" },
            { label: t("historicalKind"), value: "historical" },
          ]}
          fullWidth
        />

        {kind === "saved" ? (
          <>
            <Group justify="space-between" align="flex-end" gap="md">
              <Stack gap="xs" style={{ flex: 1 }}>
                <SegmentedControl
                  value={savedScope}
                  onChange={(value) =>
                    onSavedScopeChange(toSavedMemoryScopeValue(value))
                  }
                  data={[
                    { label: t("agentScope"), value: "agent" },
                    { label: t("userScope"), value: "user" },
                  ]}
                />
                <TextInput
                  leftSection={<IconSearch size={rem(16)} />}
                  value={savedQuery}
                  placeholder={t("savedSearchPlaceholder")}
                  onChange={(event) =>
                    onSavedQueryChange(event.currentTarget.value)
                  }
                />
              </Stack>
              <Button
                leftSection={<IconPlus size={rem(16)} />}
                onClick={onStartCreate}
              >
                {t("create")}
              </Button>
            </Group>

            {actionError && <Alert color="red">{actionError}</Alert>}

            <SavedMemoryList
              state={savedListState}
              deletingId={deletingId}
              onEdit={onStartEdit}
              onDelete={onDeleteMemory}
            />
            {savedListState.type === "LOADED" && (
              <PaginationStatus
                state={paginationState}
                endRef={scrollEndRef}
                onRetry={onRetryNextPage}
              />
            )}
          </>
        ) : (
          <Stack gap="md">
            <Text size="sm" c="dimmed">
              {t("historicalDescription")}
            </Text>
            <SegmentedControl
              value={historicalScope}
              onChange={(value) =>
                onHistoricalScopeChange(toHistoricalMemoryScopeValue(value))
              }
              data={[
                { label: t("teamScope"), value: "team" },
                { label: t("personalScope"), value: "user" },
              ]}
            />
            {actionError && <Alert color="red">{actionError}</Alert>}
            {historicalView === "overview" ? (
              <>
                <ConsolidatedMemory state={consolidatedState} />
                <Button
                  variant="default"
                  rightSection={<IconChevronRight size={rem(16)} />}
                  onClick={() => onHistoricalViewChange("sessions")}
                >
                  {t("viewSessionMemories")}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="subtle"
                  leftSection={<IconArrowLeft size={rem(16)} />}
                  onClick={() => onHistoricalViewChange("overview")}
                  style={{ alignSelf: "flex-start" }}
                >
                  {t("backToIntegrated")}
                </Button>
                <TextInput
                  leftSection={<IconSearch size={rem(16)} />}
                  value={historicalQuery}
                  placeholder={t("historicalSearchPlaceholder")}
                  onChange={(event) =>
                    onHistoricalQueryChange(event.currentTarget.value)
                  }
                />
                <HistoricalMemoryList
                  state={historicalListState}
                  scope={historicalScope}
                />
                {historicalListState.type === "LOADED" && (
                  <PaginationStatus
                    state={paginationState}
                    endRef={scrollEndRef}
                    onRetry={onRetryNextPage}
                  />
                )}
              </>
            )}
          </Stack>
        )}
      </Stack>
      <MemoryDraftModal
        draftState={draftState}
        saving={saving}
        onCancel={onCancelDraft}
        onDraftChange={onDraftChange}
        onSave={onSaveDraft}
      />
    </Box>
  );
}
