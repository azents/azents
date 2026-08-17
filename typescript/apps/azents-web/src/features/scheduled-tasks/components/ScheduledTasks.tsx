"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Modal,
  NavLink,
  Paper,
  rem,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  ThemeIcon,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCalendarClock,
  IconChevronRight,
  IconCircleDot,
  IconClock,
  IconPencil,
  IconPlus,
  IconRoute,
  IconX,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { formatLocalizedDate } from "@/shared/lib/date-format";
import { useLocale } from "@/shared/providers/locale";
import type { ScheduledTasksContainerOutput } from "../containers/useScheduledTasksContainer";
import type { ScheduledTaskDraft } from "../types";
import type { SupportedLocale } from "@/shared/lib/locale";
import type {
  ScheduledTaskCurrentCycleResponse,
  ScheduledTaskResponse,
} from "@azents/public-client";

function formatTimestamp(value: string, locale: SupportedLocale): string {
  return formatLocalizedDate(new Date(value), locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function executionColor(
  state: ScheduledTaskResponse["execution_state"],
): string {
  switch (state) {
    case "idle":
      return "gray";
    case "admitted":
      return "yellow";
    case "running":
      return "blue";
    case "running_with_pending":
      return "orange";
  }
}

function scheduleSummary(
  task: ScheduledTaskResponse,
  locale: SupportedLocale,
): string {
  if (task.schedule_type === "once") {
    return task.scheduled_at === null
      ? "—"
      : formatTimestamp(task.scheduled_at, locale);
  }
  return `${task.cron_expression ?? "—"} · ${task.timezone ?? "—"}`;
}

function TaskList({
  tasks,
  selectedTaskId,
  locale,
  onSelectTask,
}: {
  tasks: ScheduledTaskResponse[];
  selectedTaskId: string | null;
  locale: SupportedLocale;
  onSelectTask: (taskId: string | null) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.scheduledTasks");

  if (tasks.length === 0) {
    return (
      <Stack align="center" gap="xs" py="xl" px="md">
        <ThemeIcon variant="light" color="gray" radius="xl" size="xl">
          <IconCalendarClock size={rem(24)} />
        </ThemeIcon>
        <Text fw={600}>{t("emptyTitle")}</Text>
        <Text size="sm" c="dimmed" ta="center">
          {t("emptyDescription")}
        </Text>
      </Stack>
    );
  }

  return (
    <Stack gap={0}>
      {tasks.map((task, index) => (
        <Box key={task.id}>
          {index > 0 && <Divider />}
          <NavLink
            component="button"
            type="button"
            active={task.id === selectedTaskId}
            onClick={() => onSelectTask(task.id)}
            py="md"
            label={
              <Text fw={600} size="sm" truncate>
                {task.title}
              </Text>
            }
            description={
              <Stack gap={rem(3)} mt={rem(4)}>
                <Badge
                  size="xs"
                  variant="light"
                  color={executionColor(task.execution_state)}
                  w="fit-content"
                >
                  {t(`executionState.${task.execution_state}`)}
                </Badge>
                <Text size="xs" c="dimmed" truncate>
                  {scheduleSummary(task, locale)}
                </Text>
              </Stack>
            }
            rightSection={<IconChevronRight size={rem(16)} />}
          />
        </Box>
      ))}
    </Stack>
  );
}

function CurrentCycle({
  cycle,
  locale,
}: {
  cycle: ScheduledTaskCurrentCycleResponse;
  locale: SupportedLocale;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.scheduledTasks");
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Box>
          <Text fw={600}>{cycle.progress_title ?? t("cycle.inProgress")}</Text>
          <Text size="sm" c="dimmed">
            {t("cycle.scheduledFor", {
              value: formatTimestamp(cycle.scheduled_for, locale),
            })}
          </Text>
        </Box>
        <Badge color={cycle.phase === "started" ? "blue" : "yellow"}>
          {t(`cycle.phase.${cycle.phase}`)}
        </Badge>
      </Group>
      {cycle.started_at !== null && (
        <Text size="sm" c="dimmed">
          {t("cycle.startedAt", {
            value: formatTimestamp(cycle.started_at, locale),
          })}
        </Text>
      )}
      {cycle.ordered_tasks.length > 0 && (
        <Stack gap="xs">
          <Text size="xs" fw={700} c="dimmed" tt="uppercase">
            {t("cycle.orderedTasks")}
          </Text>
          {cycle.ordered_tasks.map((task, index) => (
            <Group key={`${index}-${task}`} gap="xs" wrap="nowrap">
              <IconCircleDot
                size={rem(14)}
                color="var(--mantine-color-dimmed)"
              />
              <Text size="sm" style={{ overflowWrap: "anywhere" }}>
                {task}
              </Text>
            </Group>
          ))}
        </Stack>
      )}
    </Stack>
  );
}

function TaskDetail({
  detail,
  mutationBusy,
  locale,
  onOpenEdit,
  onRequestCancel,
}: Pick<
  ScheduledTasksContainerOutput,
  "detail" | "mutationBusy" | "onOpenEdit" | "onRequestCancel"
> & {
  locale: SupportedLocale;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.scheduledTasks");

  if (detail === null) {
    return (
      <Center mih={rem(320)} p="xl">
        <Stack align="center" gap="xs">
          <ThemeIcon variant="light" color="gray" radius="xl" size="xl">
            <IconRoute size={rem(24)} />
          </ThemeIcon>
          <Text fw={600}>{t("selectTitle")}</Text>
          <Text size="sm" c="dimmed" ta="center">
            {t("selectDescription")}
          </Text>
        </Stack>
      </Center>
    );
  }
  if (detail.type === "LOADING") {
    return (
      <Center mih={rem(320)}>
        <Loader size="sm" />
      </Center>
    );
  }
  if (detail.type === "ERROR") {
    return (
      <Alert color="red" icon={<IconAlertCircle size={rem(18)} />} m="md">
        {detail.message}
      </Alert>
    );
  }

  const task = detail.task;
  return (
    <Stack gap="lg" p={{ base: "md", sm: "lg" }}>
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Box flex={{ base: "0 0 100%", sm: "1 1 auto" }} miw={0}>
          <Text fw={700} size="lg" style={{ overflowWrap: "anywhere" }}>
            {task.title}
          </Text>
          <Badge
            mt="xs"
            variant="light"
            color={executionColor(task.execution_state)}
          >
            {t(`executionState.${task.execution_state}`)}
          </Badge>
          <Text size="sm" c="dimmed" mt="xs">
            {t("nextEligible", {
              value: formatTimestamp(task.next_eligible_at, locale),
            })}
          </Text>
        </Box>
        <Group gap="xs" w={{ base: "100%", sm: "auto" }} ml={{ sm: "auto" }}>
          <Button
            variant="default"
            size="compact-sm"
            leftSection={<IconPencil size={rem(14)} />}
            disabled={mutationBusy}
            onClick={() => onOpenEdit(task)}
          >
            {t("edit")}
          </Button>
          <Button
            variant="subtle"
            color="red"
            size="compact-sm"
            leftSection={<IconX size={rem(14)} />}
            disabled={mutationBusy}
            onClick={() => onRequestCancel(task)}
          >
            {t("cancelTask")}
          </Button>
        </Group>
      </Group>

      <Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          {t("objective")}
        </Text>
        <Text
          mt="xs"
          style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
        >
          {task.objective}
        </Text>
      </Box>

      <Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          {t("schedule")}
        </Text>
        <Group gap="xs" mt="xs" wrap="nowrap" align="flex-start">
          <IconClock size={rem(16)} />
          <Box>
            <Text size="sm" fw={600}>
              {t(`scheduleType.${task.schedule_type}`)}
            </Text>
            <Text size="sm" c="dimmed">
              {scheduleSummary(task, locale)}
            </Text>
          </Box>
        </Group>
      </Box>

      <Box>
        <Text size="xs" fw={700} c="dimmed" tt="uppercase">
          {t("deliveryTarget")}
        </Text>
        {task.target === null ? (
          <Text size="sm" c="dimmed" mt="xs">
            {t("sessionOnly")}
          </Text>
        ) : (
          <Stack gap={rem(2)} mt="xs">
            <Text size="sm" fw={600}>
              {task.target.label}
            </Text>
            <Text size="sm" c="dimmed">
              {task.target.provider} · {t(`location.${task.target.location}`)}
            </Text>
          </Stack>
        )}
      </Box>

      <Divider />
      <Box>
        <Text fw={700}>{t("cycle.title")}</Text>
        <Text size="sm" c="dimmed">
          {t("cycle.description")}
        </Text>
      </Box>
      {detail.cycleLoading && (
        <Center py="md">
          <Loader size="sm" />
        </Center>
      )}
      {detail.cycleError !== null && (
        <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
          {detail.cycleError}
        </Alert>
      )}
      {!detail.cycleLoading &&
        detail.cycleError === null &&
        detail.cycle === null && (
          <Text size="sm" c="dimmed">
            {t("cycle.empty")}
          </Text>
        )}
      {!detail.cycleLoading &&
        detail.cycleError === null &&
        detail.cycle !== null && (
          <CurrentCycle cycle={detail.cycle} locale={locale} />
        )}
    </Stack>
  );
}

function TaskForm({
  form,
  mutationBusy,
  actionError,
  onCloseForm,
  onChangeDraft,
  onSave,
}: Pick<
  ScheduledTasksContainerOutput,
  | "form"
  | "mutationBusy"
  | "actionError"
  | "onCloseForm"
  | "onChangeDraft"
  | "onSave"
>): React.ReactElement {
  const t = useTranslations("workspace.agents.scheduledTasks");
  if (form.type === "CLOSED") {
    return <></>;
  }
  const bindingData = form.bindings.map((binding) => ({
    value: binding.id,
    label: `${binding.resource_label} · ${binding.provider} · ${t(
      `location.${binding.conversation_location}`,
    )}`,
  }));
  const updateDraft = (values: Partial<ScheduledTaskDraft>): void => {
    onChangeDraft({ ...form.draft, ...values });
  };

  return (
    <Modal
      opened
      onClose={onCloseForm}
      title={
        form.type === "CREATE" ? t("form.createTitle") : t("form.editTitle")
      }
      size="lg"
      scrollAreaComponent={ScrollArea.Autosize}
      centered
    >
      <Stack gap="md">
        {actionError !== null && (
          <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
            {actionError.type === "CONFLICT"
              ? t("conflictError")
              : actionError.message}
          </Alert>
        )}
        {form.error !== null && (
          <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
            {t(`validation.${form.error}`)}
          </Alert>
        )}
        <TextInput
          label={t("form.titleLabel")}
          value={form.draft.title}
          maxLength={120}
          disabled={mutationBusy}
          onChange={(event) =>
            updateDraft({ title: event.currentTarget.value })
          }
        />
        <Textarea
          label={t("form.objectiveLabel")}
          description={t("form.objectiveDescription")}
          value={form.draft.objective}
          maxLength={3000}
          minRows={4}
          autosize
          disabled={mutationBusy}
          onChange={(event) =>
            updateDraft({ objective: event.currentTarget.value })
          }
        />
        <Box>
          <Text size="sm" fw={500} mb="xs">
            {t("form.scheduleTypeLabel")}
          </Text>
          <SegmentedControl
            fullWidth
            value={form.draft.scheduleType}
            disabled={mutationBusy}
            data={[
              { value: "once", label: t("scheduleType.once") },
              { value: "cron", label: t("scheduleType.cron") },
            ]}
            onChange={(value) =>
              updateDraft({ scheduleType: value === "cron" ? "cron" : "once" })
            }
          />
        </Box>
        {form.draft.scheduleType === "once" ? (
          <TextInput
            type="datetime-local"
            label={t("form.oneTimeLabel")}
            description={t("form.oneTimeDescription")}
            value={form.draft.at}
            disabled={mutationBusy}
            onChange={(event) => updateDraft({ at: event.currentTarget.value })}
          />
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="md">
            <TextInput
              label={t("form.cronLabel")}
              description={t("form.cronDescription")}
              placeholder="0 9 * * 1-5"
              maxLength={256}
              value={form.draft.cron}
              disabled={mutationBusy}
              onChange={(event) =>
                updateDraft({ cron: event.currentTarget.value })
              }
            />
            <TextInput
              label={t("form.timezoneLabel")}
              description={t("form.timezoneDescription")}
              placeholder="Asia/Seoul"
              maxLength={128}
              value={form.draft.timezone}
              disabled={mutationBusy}
              onChange={(event) =>
                updateDraft({ timezone: event.currentTarget.value })
              }
            />
          </SimpleGrid>
        )}
        <Select
          label={t("form.bindingLabel")}
          description={t("form.bindingDescription")}
          placeholder={
            form.bindingsLoading
              ? t("form.bindingLoading")
              : t("form.bindingPlaceholder")
          }
          data={bindingData}
          value={form.draft.channelId}
          searchable
          clearable
          disabled={
            mutationBusy || form.bindingsLoading || form.draft.sessionId === ""
          }
          rightSection={form.bindingsLoading ? <Loader size="xs" /> : null}
          onChange={(value) => updateDraft({ channelId: value })}
        />
        {form.bindingsError !== null && (
          <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
            {form.bindingsError}
          </Alert>
        )}
        <Group justify="flex-end">
          <Button
            variant="default"
            disabled={mutationBusy}
            onClick={onCloseForm}
          >
            {t("cancel")}
          </Button>
          <Button loading={mutationBusy} onClick={onSave}>
            {form.type === "CREATE" ? t("create") : t("save")}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function ScheduledTasks({
  state,
  detail,
  form,
  selectedTaskId,
  cancelTarget,
  mutationBusy,
  actionError,
  onSelectTask,
  onOpenCreate,
  onOpenEdit,
  onCloseForm,
  onChangeDraft,
  onSave,
  onRequestCancel,
  onCloseCancel,
  onConfirmCancel,
}: ScheduledTasksContainerOutput): React.ReactElement {
  const t = useTranslations("workspace.agents.scheduledTasks");
  const { locale } = useLocale();

  return (
    <>
      <TaskForm
        form={form}
        mutationBusy={mutationBusy}
        actionError={actionError}
        onCloseForm={onCloseForm}
        onChangeDraft={onChangeDraft}
        onSave={onSave}
      />
      <Modal
        opened={cancelTarget !== null}
        onClose={onCloseCancel}
        title={t("cancelConfirmTitle")}
        centered
      >
        <Stack gap="md">
          {actionError !== null && (
            <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
              {actionError.type === "CONFLICT"
                ? t("conflictError")
                : actionError.message}
            </Alert>
          )}
          <Text size="sm">
            {t("cancelConfirmDescription", {
              title: cancelTarget?.title ?? "",
            })}
          </Text>
          <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
            {t("cancelEffect")}
          </Alert>
          <Group justify="flex-end">
            <Button
              variant="default"
              disabled={mutationBusy}
              onClick={onCloseCancel}
            >
              {t("keepTask")}
            </Button>
            <Button
              color="red"
              loading={mutationBusy}
              onClick={onConfirmCancel}
            >
              {t("cancelTask")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Box
        flex={1}
        mih={0}
        style={{ display: "flex", flexDirection: "column" }}
      >
        <ScrollArea flex={1} mih={0} type="auto">
          <Stack
            gap="lg"
            p={{ base: "md", sm: "lg" }}
            maw={rem(1180)}
            mx="auto"
            w="100%"
          >
            <Group justify="space-between" align="flex-start" wrap="wrap">
              <Box>
                <Text fw={700} size="xl">
                  {t("title")}
                </Text>
                <Text size="sm" c="dimmed">
                  {t("description")}
                </Text>
              </Box>
              <Button
                size="compact-sm"
                leftSection={<IconPlus size={rem(16)} />}
                onClick={onOpenCreate}
              >
                {t("newTask")}
              </Button>
            </Group>

            {actionError !== null && (
              <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
                {actionError.type === "CONFLICT"
                  ? t("conflictError")
                  : actionError.message}
              </Alert>
            )}

            {state.type === "LOADING" && (
              <Center py="xl">
                <Loader />
              </Center>
            )}
            {state.type === "ERROR" && (
              <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
                {state.message}
              </Alert>
            )}
            {state.type === "LOADED" && (
              <SimpleGrid
                cols={{ base: 1, md: 2 }}
                spacing="lg"
                verticalSpacing="lg"
              >
                <Paper withBorder radius="lg" style={{ overflow: "hidden" }}>
                  <Group justify="space-between" p="md">
                    <Group gap="xs">
                      <Text fw={700}>{t("listTitle")}</Text>
                      <Badge variant="light">{state.tasks.length}</Badge>
                    </Group>
                  </Group>
                  <Divider />
                  <TaskList
                    tasks={state.tasks}
                    selectedTaskId={selectedTaskId}
                    locale={locale}
                    onSelectTask={onSelectTask}
                  />
                </Paper>
                <Paper withBorder radius="lg" style={{ overflow: "hidden" }}>
                  <TaskDetail
                    detail={detail}
                    mutationBusy={mutationBusy}
                    locale={locale}
                    onOpenEdit={onOpenEdit}
                    onRequestCancel={onRequestCancel}
                  />
                </Paper>
              </SimpleGrid>
            )}
          </Stack>
        </ScrollArea>
      </Box>
    </>
  );
}
