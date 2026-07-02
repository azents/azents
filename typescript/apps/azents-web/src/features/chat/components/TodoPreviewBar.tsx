"use client";

/**
 * inputinput to attached session goal/todo progress preview.
 */

import {
  Badge,
  Box,
  Button,
  Drawer,
  Group,
  Modal,
  Progress,
  rem,
  Stack,
  Text,
  Textarea,
  UnstyledButton,
} from "@mantine/core";
import {
  IconChevronDown,
  IconChevronUp,
  IconListCheck,
  IconSquare,
  IconSquareCheck,
  IconTargetArrow,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { type ReactElement, useMemo, useState } from "react";
import type {
  GoalStateSnapshot,
  GoalStatus,
  TodoItem,
  TodoStateSnapshot,
  TodoStatus,
} from "../types";

interface TodoPreviewBarProps {
  goal: GoalStateSnapshot | null;
  isMobile: boolean;
  todo: TodoStateSnapshot;
  onClearGoal?: () => Promise<boolean>;
  onUpdateGoal?: (objective: string) => Promise<boolean>;
  onPauseGoal?: () => Promise<boolean>;
  onResumeGoal?: (hint?: string) => Promise<boolean>;
}

interface TodoListContentProps {
  completedPercent: number;
  completedText: string;
  expandedItems: Set<string>;
  todo: TodoStateSnapshot;
  onToggleExpanded: (key: string) => void;
}

function iconColor(status: TodoStatus): string {
  switch (status) {
    case "in_progress":
      return "var(--mantine-color-blue-5)";
    case "completed":
    case "pending":
      return "var(--mantine-color-dimmed)";
  }
}

function rowTextColor(status: TodoStatus): string {
  switch (status) {
    case "completed":
      return "dimmed";
    case "in_progress":
    case "pending":
      return "var(--mantine-color-text)";
  }
}

function goalStatusColor(status: GoalStatus): string {
  switch (status) {
    case "active":
      return "blue";
    case "paused":
      return "gray";
    case "blocked":
      return "orange";
    case "complete":
      return "green";
  }
}

function TodoCheckboxIcon({
  status,
  color,
  size = 14,
}: {
  status: TodoStatus;
  color?: string;
  size?: number;
}): ReactElement {
  const Icon = status === "completed" ? IconSquareCheck : IconSquare;
  return (
    <Icon
      aria-hidden="true"
      size={size}
      stroke={1.8}
      color={color ?? iconColor(status)}
      style={{ flexShrink: 0 }}
    />
  );
}

function previewItem(items: TodoItem[]): TodoItem | null {
  return (
    items.find((item) => item.status === "in_progress") ??
    items.find((item) => item.status === "pending") ??
    null
  );
}

function todoItemKey(todoItem: TodoItem, index: number): string {
  return `${todoItem.status}:${todoItem.content}:${index}`;
}

function SheetTitle({ title }: { title: string }): ReactElement {
  return (
    <Group gap="xs" wrap="nowrap">
      <IconListCheck
        aria-hidden="true"
        size={18}
        stroke={1.8}
        color="var(--mantine-color-dimmed)"
      />
      <Text fw={600}>{title}</Text>
    </Group>
  );
}

function SectionTitle({ children }: { children: string }): ReactElement {
  return (
    <Text size="xs" c="dimmed" fw={700} tt="uppercase" lts={rem(0.4)}>
      {children}
    </Text>
  );
}

function TodoRowText({
  expanded,
  item,
}: {
  expanded: boolean;
  item: TodoItem;
}): ReactElement {
  if (expanded) {
    return (
      <Text
        size="sm"
        c={rowTextColor(item.status)}
        lh={rem(20)}
        style={{
          flex: 1,
          minWidth: 0,
          textDecoration: item.status === "completed" ? "line-through" : "none",
        }}
      >
        {item.content}
      </Text>
    );
  }

  return (
    <Text
      size="sm"
      c={rowTextColor(item.status)}
      lh={rem(20)}
      truncate="end"
      style={{
        flex: 1,
        minWidth: 0,
        textDecoration: item.status === "completed" ? "line-through" : "none",
      }}
    >
      {item.content}
    </Text>
  );
}

function GoalSection({
  goal,
  onClearGoal,
  onUpdateGoal,
  onPauseGoal,
  onResumeGoal,
}: {
  goal: GoalStateSnapshot;
  onClearGoal?: () => Promise<boolean>;
  onUpdateGoal?: (objective: string) => Promise<boolean>;
  onPauseGoal?: () => Promise<boolean>;
  onResumeGoal?: (hint?: string) => Promise<boolean>;
}): ReactElement {
  const t = useTranslations("chat.todo");
  const status = goal.status ?? "active";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(goal.objective ?? "");
  const [submitting, setSubmitting] = useState(false);
  const [confirmAction, setConfirmAction] = useState<
    "delete" | "pause" | "resume" | null
  >(null);
  const [resumeHint, setResumeHint] = useState("");

  const saveGoal = (): void => {
    const nextObjective = draft.trim();
    if (!onUpdateGoal || nextObjective === "") {
      return;
    }
    setSubmitting(true);
    void onUpdateGoal(nextObjective).then((ok) => {
      setSubmitting(false);
      if (ok) {
        setEditing(false);
      }
    });
  };

  const clearGoal = (): void => {
    if (!onClearGoal) {
      return;
    }
    setSubmitting(true);
    void onClearGoal()
      .then((ok) => {
        if (ok) {
          closeConfirm();
        }
      })
      .finally(() => setSubmitting(false));
  };

  const closeConfirm = (): void => {
    setConfirmAction(null);
    setResumeHint("");
  };

  const confirmGoalAction = (): void => {
    const action = confirmAction;
    if (action === "delete") {
      clearGoal();
      return;
    }
    if (action === "pause") {
      if (!onPauseGoal) {
        return;
      }
      setSubmitting(true);
      void onPauseGoal().then((ok) => {
        setSubmitting(false);
        if (ok) {
          closeConfirm();
        }
      });
      return;
    }
    if (action === "resume") {
      if (!onResumeGoal) {
        return;
      }
      setSubmitting(true);
      void onResumeGoal(resumeHint).then((ok) => {
        setSubmitting(false);
        if (ok) {
          closeConfirm();
        }
      });
    }
  };

  const canPause = status === "active";
  const canResume = status === "paused" || status === "blocked";

  const confirmTitle = (): string => {
    switch (confirmAction) {
      case "delete":
        return t("deleteGoalConfirmTitle");
      case "pause":
        return t("pauseGoalConfirmTitle");
      case "resume":
        return t("resumeGoalConfirmTitle");
      case null:
        return "";
    }
  };

  const confirmDescription = (): string => {
    switch (confirmAction) {
      case "delete":
        return t("deleteGoalConfirmDescription");
      case "pause":
        return t("pauseGoalConfirmDescription");
      case "resume":
        return t("resumeGoalConfirmDescription");
      case null:
        return "";
    }
  };

  const confirmLabel = (): string => {
    switch (confirmAction) {
      case "delete":
        return t("deleteGoal");
      case "pause":
        return t("pauseGoal");
      case "resume":
        return t("resumeGoal");
      case null:
        return "";
    }
  };

  return (
    <>
      <Stack gap="xs">
        <SectionTitle>{t("goalSection")}</SectionTitle>
        <Stack
          gap="sm"
          p="sm"
          style={{
            border: `${rem(1)} solid var(--mantine-color-default-border)`,
            borderRadius: rem(8),
            background: "var(--mantine-color-body)",
          }}
        >
          <Group
            gap="xs"
            justify="space-between"
            align="flex-start"
            wrap="nowrap"
          >
            <Group
              gap="xs"
              align="flex-start"
              wrap="nowrap"
              style={{ flex: 1, minWidth: 0 }}
            >
              <IconTargetArrow
                aria-hidden="true"
                size={18}
                stroke={1.8}
                color="var(--mantine-color-blue-5)"
                style={{ flexShrink: 0, marginTop: rem(2) }}
              />
              {editing ? (
                <Textarea
                  value={draft}
                  onChange={(event) => setDraft(event.currentTarget.value)}
                  autosize
                  minRows={1}
                  maxRows={5}
                  size="xs"
                  style={{ flex: 1, minWidth: 0 }}
                  styles={{ input: { fontSize: rem(16) } }}
                  aria-label={t("editGoal")}
                />
              ) : (
                <Text size="sm" lh={rem(20)} style={{ flex: 1, minWidth: 0 }}>
                  {goal.objective}
                </Text>
              )}
            </Group>
            <Badge
              variant="light"
              color={goalStatusColor(status)}
              style={{ flexShrink: 0, overflow: "visible" }}
            >
              {t(`goalStatus.${status}`)}
            </Badge>
          </Group>
          {status !== "active" && (
            <Text size="xs" c="dimmed">
              {t(`goalStatusDescription.${status}`)}
            </Text>
          )}
          <Group gap="xs" justify="flex-end">
            {editing ? (
              <>
                <Button
                  size="xs"
                  variant="subtle"
                  onClick={() => setEditing(false)}
                >
                  {t("cancelGoalEdit")}
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  loading={submitting}
                  onClick={saveGoal}
                >
                  {t("saveGoal")}
                </Button>
              </>
            ) : (
              <>
                {canPause && (
                  <Button
                    size="xs"
                    variant="subtle"
                    loading={submitting}
                    disabled={!onPauseGoal}
                    onClick={() => setConfirmAction("pause")}
                  >
                    {t("pauseGoal")}
                  </Button>
                )}
                {canResume && (
                  <Button
                    size="xs"
                    variant="light"
                    loading={submitting}
                    disabled={!onResumeGoal}
                    onClick={() => setConfirmAction("resume")}
                  >
                    {t("resumeGoal")}
                  </Button>
                )}
                <Button
                  size="xs"
                  variant="subtle"
                  disabled={!onUpdateGoal}
                  onClick={() => setEditing(true)}
                >
                  {t("editGoal")}
                </Button>
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  loading={submitting}
                  disabled={!onClearGoal}
                  onClick={() => setConfirmAction("delete")}
                >
                  {t("deleteGoal")}
                </Button>
              </>
            )}
          </Group>
        </Stack>
      </Stack>
      <Modal
        opened={confirmAction !== null}
        onClose={closeConfirm}
        title={confirmTitle()}
        centered
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">{confirmDescription()}</Text>
          {confirmAction === "resume" && (
            <Textarea
              value={resumeHint}
              onChange={(event) => setResumeHint(event.currentTarget.value)}
              label={t("resumeHintLabel")}
              description={t("resumeHintDescription")}
              placeholder={t("resumeHintPlaceholder")}
              autosize
              minRows={2}
              maxRows={5}
              size="sm"
              maxLength={2000}
              styles={{ input: { fontSize: rem(16) } }}
            />
          )}
          <Group justify="flex-end" gap="xs">
            <Button size="xs" variant="subtle" onClick={closeConfirm}>
              {t("cancelGoalEdit")}
            </Button>
            <Button
              size="xs"
              color={confirmAction === "delete" ? "red" : "blue"}
              loading={submitting}
              onClick={confirmGoalAction}
            >
              {confirmLabel()}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function TodoListContent({
  completedPercent,
  completedText,
  expandedItems,
  todo,
  onToggleExpanded,
}: TodoListContentProps): ReactElement {
  const t = useTranslations("chat.todo");
  return (
    <Stack gap="sm">
      <SectionTitle>{t("todoSection")}</SectionTitle>
      <Stack gap={rem(6)}>
        <Group justify="space-between" wrap="nowrap">
          <Text size="sm" c="dimmed">
            {completedText}
          </Text>
          <Text size="sm" c="dimmed" style={{ flexShrink: 0 }}>
            {Math.round(completedPercent)}%
          </Text>
        </Group>
        <Progress value={completedPercent} size="xs" radius="xl" />
      </Stack>
      <Stack
        gap={0}
        style={{
          border: `${rem(1)} solid var(--mantine-color-default-border)`,
          borderRadius: rem(6),
          overflow: "hidden",
        }}
      >
        {todo.items.map((todoItem, index) => {
          const key = todoItemKey(todoItem, index);
          const expanded = expandedItems.has(key);
          return (
            <UnstyledButton
              key={key}
              w="100%"
              onClick={() => onToggleExpanded(key)}
              aria-expanded={expanded}
              style={{
                display: "block",
                textAlign: "left",
              }}
            >
              <Group
                gap="xs"
                align="center"
                wrap="nowrap"
                px="sm"
                py={rem(6)}
                mih={rem(40)}
                style={{
                  borderTop:
                    index === 0
                      ? "none"
                      : `${rem(1)} solid var(--mantine-color-default-border)`,
                  background: "var(--mantine-color-body)",
                }}
              >
                <Box
                  h={rem(20)}
                  style={{
                    alignItems: "center",
                    display: "flex",
                    flexShrink: 0,
                  }}
                >
                  <TodoCheckboxIcon status={todoItem.status} size={15} />
                </Box>
                <TodoRowText expanded={expanded} item={todoItem} />
                {expanded ? (
                  <IconChevronUp
                    aria-hidden="true"
                    size={14}
                    stroke={1.8}
                    color="var(--mantine-color-dimmed)"
                    style={{ flexShrink: 0 }}
                  />
                ) : (
                  <IconChevronDown
                    aria-hidden="true"
                    size={14}
                    stroke={1.8}
                    color="var(--mantine-color-dimmed)"
                    style={{ flexShrink: 0 }}
                  />
                )}
              </Group>
            </UnstyledButton>
          );
        })}
      </Stack>
    </Stack>
  );
}

export function TodoPreviewBar({
  goal,
  isMobile,
  todo,
  onClearGoal,
  onUpdateGoal,
  onPauseGoal,
  onResumeGoal,
}: TodoPreviewBarProps): ReactElement | null {
  const t = useTranslations("chat.todo");
  const [opened, setOpened] = useState(false);
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());
  const item = previewItem(todo.items);
  const activeGoal =
    goal?.objective && goal.status !== "complete" ? goal : null;
  const hasTodo = todo.items.length > 0 && item !== null;

  const completedCount = todo.items.filter(
    (todoItem) => todoItem.status === "completed",
  ).length;
  const completedPercent =
    todo.items.length === 0 ? 0 : (completedCount / todo.items.length) * 100;
  const title = t("progressTitle");
  const openLabel = t("openLabel");
  const completedText = t("completed", {
    completedCount,
    totalCount: todo.items.length,
  });

  const previewText = activeGoal?.objective ?? item?.content ?? null;
  const previewStatus = activeGoal?.status ?? null;

  const toggleExpanded = (key: string): void => {
    setExpandedItems((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const content = useMemo(
    () => (
      <Stack gap="lg">
        {activeGoal !== null && (
          <GoalSection
            goal={activeGoal}
            onClearGoal={onClearGoal}
            onUpdateGoal={onUpdateGoal}
            onPauseGoal={onPauseGoal}
            onResumeGoal={onResumeGoal}
          />
        )}
        {hasTodo && (
          <TodoListContent
            completedPercent={completedPercent}
            completedText={completedText}
            expandedItems={expandedItems}
            todo={todo}
            onToggleExpanded={toggleExpanded}
          />
        )}
      </Stack>
    ),
    [
      activeGoal,
      completedPercent,
      completedText,
      expandedItems,
      hasTodo,
      onClearGoal,
      onUpdateGoal,
      onPauseGoal,
      onResumeGoal,
      todo,
    ],
  );

  if (previewText === null) {
    return null;
  }

  return (
    <>
      <UnstyledButton
        onClick={() => setOpened(true)}
        aria-label={openLabel}
        style={{
          display: "block",
          left: "var(--mantine-radius-default)",
          minWidth: 0,
          overflow: "hidden",
          position: "absolute",
          bottom: "100%",
          right: "var(--mantine-radius-default)",
          zIndex: 1,
        }}
      >
        <Group
          gap={rem(5)}
          wrap="nowrap"
          px={rem(8)}
          h={rem(22)}
          style={{
            maxWidth: "100%",
            minWidth: 0,
            overflow: "hidden",
            border: `${rem(1)} solid var(--mantine-color-default-border)`,
            borderBottom: 0,
            borderTopLeftRadius: rem(6),
            borderTopRightRadius: rem(6),
            background: "var(--mantine-color-body)",
          }}
        >
          {activeGoal !== null && (
            <IconTargetArrow
              aria-hidden="true"
              size={13}
              stroke={1.8}
              color="var(--mantine-color-dimmed)"
              style={{ flexShrink: 0 }}
            />
          )}
          {activeGoal === null && hasTodo && (
            <TodoCheckboxIcon
              status={item.status}
              color="var(--mantine-color-dimmed)"
              size={13}
            />
          )}
          <Text
            size="xs"
            c="dimmed"
            fw={400}
            truncate="end"
            style={{
              display: "block",
              flex: "1 1 auto",
              maxWidth: "100%",
              minWidth: 0,
              overflow: "hidden",
            }}
          >
            {previewText}
          </Text>
          {previewStatus === "paused" || previewStatus === "blocked" ? (
            <Badge
              size="xs"
              variant="light"
              color={goalStatusColor(previewStatus)}
              style={{ flexShrink: 0, overflow: "visible" }}
            >
              {t(`goalStatus.${previewStatus}`)}
            </Badge>
          ) : previewStatus === null ? (
            <Box
              px={rem(6)}
              style={{
                borderRadius: rem(999),
                background: "var(--mantine-color-default-hover)",
                flexShrink: 0,
              }}
            >
              <Text c="dimmed" fz={rem(11)} lh={rem(16)}>
                {completedCount}/{todo.items.length}
              </Text>
            </Box>
          ) : null}
        </Group>
      </UnstyledButton>
      {isMobile ? (
        <Drawer
          opened={opened}
          onClose={() => setOpened(false)}
          title={<SheetTitle title={title} />}
          position="bottom"
          size="calc(100dvh - env(safe-area-inset-top))"
          keepMounted
          transitionProps={{
            transition: "slide-up",
            duration: 180,
            exitDuration: 180,
          }}
          styles={{
            content: {
              borderTopLeftRadius: rem(12),
              borderTopRightRadius: rem(12),
              display: "flex",
              flexDirection: "column",
              height: "calc(100dvh - env(safe-area-inset-top))",
              maxHeight: "calc(100dvh - env(safe-area-inset-top))",
            },
            header: {
              flexShrink: 0,
            },
            body: {
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              paddingBottom:
                "max(var(--mantine-spacing-md), env(safe-area-inset-bottom))",
            },
          }}
        >
          {content}
        </Drawer>
      ) : (
        <Modal
          opened={opened}
          onClose={() => setOpened(false)}
          title={<SheetTitle title={title} />}
          centered
          size="md"
        >
          {content}
        </Modal>
      )}
    </>
  );
}
