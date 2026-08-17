"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import { parseScheduledTaskDraft, toLocalDateTimeInput } from "../schemas";
import type {
  ScheduledTaskActionError,
  ScheduledTaskDetailState,
  ScheduledTaskDraft,
  ScheduledTaskFormState,
  ScheduledTasksState,
} from "../types";
import type {
  AgentResponse,
  ScheduledTaskResponse,
} from "@azents/public-client";

export interface ScheduledTasksContainerProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  initialTaskId: string | null;
  openInitialTaskForEdit: boolean;
}

export interface ScheduledTasksContainerOutput {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  state: ScheduledTasksState;
  detail: ScheduledTaskDetailState | null;
  form: ScheduledTaskFormState;
  selectedTaskId: string | null;
  cancelTarget: ScheduledTaskResponse | null;
  mutationBusy: boolean;
  actionError: ScheduledTaskActionError | null;
  onSelectTask: (taskId: string | null) => void;
  onOpenCreate: () => void;
  onOpenEdit: (task: ScheduledTaskResponse) => void;
  onCloseForm: () => void;
  onChangeDraft: (draft: ScheduledTaskDraft) => void;
  onSave: () => void;
  onRequestCancel: (task: ScheduledTaskResponse) => void;
  onCloseCancel: () => void;
  onConfirmCancel: () => void;
}

function emptyDraft(sessionId: string): ScheduledTaskDraft {
  return {
    sessionId,
    title: "",
    objective: "",
    scheduleType: "once",
    at: "",
    cron: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    channelId: null,
  };
}

function taskDraft(task: ScheduledTaskResponse): ScheduledTaskDraft {
  return {
    sessionId: task.session.id,
    title: task.title,
    objective: task.objective,
    scheduleType: task.schedule_type,
    at:
      task.scheduled_at === null ? "" : toLocalDateTimeInput(task.scheduled_at),
    cron: task.cron_expression ?? "",
    timezone: task.timezone ?? "UTC",
    channelId: task.target?.channel_id ?? null,
  };
}

export function useScheduledTasksContainer({
  handle,
  agent,
  sessionId,
  initialTaskId,
  openInitialTaskForEdit,
}: ScheduledTasksContainerProps): ScheduledTasksContainerOutput {
  const utils = trpc.useUtils();
  const [selectedTaskIdOverride, setSelectedTaskId] = useState<string | null>(
    initialTaskId,
  );
  const [form, setForm] = useState<ScheduledTaskFormState>({ type: "CLOSED" });
  const [cancelTarget, setCancelTarget] =
    useState<ScheduledTaskResponse | null>(null);
  const [actionError, setActionError] =
    useState<ScheduledTaskActionError | null>(null);
  const initialEditHandled = useRef(false);
  const taskListInput = useMemo(
    () => ({ handle, agentId: agent.id, sessionId }),
    [agent.id, handle, sessionId],
  );

  const tasksQuery = trpc.scheduledTask.list.useQuery(taskListInput, {
    refetchInterval: 5_000,
    staleTime: 0,
  });
  const requestedTaskId =
    selectedTaskIdOverride ??
    (tasksQuery.data?.items.length === 1
      ? (tasksQuery.data.items[0]?.id ?? null)
      : null);
  const selectedTaskId =
    requestedTaskId !== null &&
    tasksQuery.isSuccess &&
    !tasksQuery.data.items.some((task) => task.id === requestedTaskId)
      ? null
      : requestedTaskId;
  const detailQuery = trpc.scheduledTask.get.useQuery(
    { handle, agentId: agent.id, taskId: selectedTaskId ?? "" },
    {
      enabled: selectedTaskId !== null,
      refetchInterval: selectedTaskId === null ? false : 5_000,
      staleTime: 0,
    },
  );
  const cycleQuery = trpc.scheduledTask.getCycle.useQuery(
    { handle, agentId: agent.id, taskId: selectedTaskId ?? "" },
    {
      enabled: selectedTaskId !== null,
      refetchInterval: selectedTaskId === null ? false : 5_000,
      staleTime: 0,
    },
  );
  const bindingsQuery = trpc.externalChannel.listSessionChannels.useQuery(
    { handle, agentId: agent.id, sessionId },
    { enabled: form.type !== "CLOSED" },
  );

  const refresh = useCallback(
    async (taskId?: string): Promise<void> => {
      await utils.scheduledTask.list.invalidate(taskListInput);
      if (taskId) {
        await Promise.all([
          utils.scheduledTask.get.invalidate({
            handle,
            agentId: agent.id,
            taskId,
          }),
          utils.scheduledTask.getCycle.invalidate({
            handle,
            agentId: agent.id,
            taskId,
          }),
        ]);
      }
    },
    [agent.id, handle, taskListInput, utils.scheduledTask],
  );

  const createMutation = trpc.scheduledTask.create.useMutation({
    onSuccess: async (task) => {
      setForm({ type: "CLOSED" });
      setSelectedTaskId(task.id);
      await refresh(task.id);
    },
    onError: (error) =>
      setActionError(
        error.data?.code === "CONFLICT"
          ? { type: "CONFLICT" }
          : { type: "ERROR", message: error.message },
      ),
  });
  const replaceMutation = trpc.scheduledTask.replace.useMutation({
    onSuccess: async (task) => {
      setForm({ type: "CLOSED" });
      setSelectedTaskId(task.id);
      await refresh(task.id);
    },
    onError: (error) =>
      setActionError(
        error.data?.code === "CONFLICT"
          ? { type: "CONFLICT" }
          : { type: "ERROR", message: error.message },
      ),
  });
  const deleteMutation = trpc.scheduledTask.delete.useMutation({
    onSuccess: async () => {
      const taskId = cancelTarget?.id;
      setCancelTarget(null);
      if (selectedTaskId === taskId) {
        setSelectedTaskId(null);
      }
      await refresh();
    },
    onError: (error) =>
      setActionError(
        error.data?.code === "CONFLICT"
          ? { type: "CONFLICT" }
          : { type: "ERROR", message: error.message },
      ),
  });

  const state: ScheduledTasksState = tasksQuery.isPending
    ? { type: "LOADING" }
    : tasksQuery.isError
      ? { type: "ERROR", message: tasksQuery.error.message }
      : { type: "LOADED", tasks: tasksQuery.data.items };
  const detail = useMemo<ScheduledTaskDetailState | null>(
    () =>
      selectedTaskId === null
        ? null
        : detailQuery.isPending
          ? { type: "LOADING" }
          : detailQuery.isError
            ? { type: "ERROR", message: detailQuery.error.message }
            : {
                type: "LOADED",
                task: detailQuery.data,
                cycle: cycleQuery.data?.current_cycle ?? null,
                cycleLoading: cycleQuery.isPending,
                cycleError: cycleQuery.error?.message ?? null,
              },
    [
      cycleQuery.data,
      cycleQuery.error,
      cycleQuery.isPending,
      detailQuery.data,
      detailQuery.error,
      detailQuery.isError,
      detailQuery.isPending,
      selectedTaskId,
    ],
  );

  const bindings =
    bindingsQuery.data?.items.filter(
      (binding) => binding.disconnected_at === null,
    ) ?? [];
  const effectiveForm =
    form.type === "CLOSED"
      ? form
      : {
          ...form,
          bindings,
          bindingsLoading: bindingsQuery.isPending,
          bindingsError: bindingsQuery.error?.message ?? null,
        };
  const mutationBusy =
    createMutation.isPending ||
    replaceMutation.isPending ||
    deleteMutation.isPending;

  useEffect(() => {
    if (
      initialEditHandled.current ||
      !openInitialTaskForEdit ||
      initialTaskId === null ||
      detail?.type !== "LOADED" ||
      detail.task.id !== initialTaskId
    ) {
      return;
    }
    initialEditHandled.current = true;
    setForm({
      type: "EDIT",
      taskId: detail.task.id,
      draft: taskDraft(detail.task),
      bindings: [],
      bindingsLoading: false,
      bindingsError: null,
      error: null,
    });
  }, [detail, initialTaskId, openInitialTaskForEdit]);

  return {
    handle,
    agent,
    sessionId,
    state,
    detail,
    form: effectiveForm,
    selectedTaskId,
    cancelTarget,
    mutationBusy,
    actionError,
    onSelectTask: (taskId) => {
      setActionError(null);
      setSelectedTaskId(taskId);
    },
    onOpenCreate: () => {
      setActionError(null);
      setForm({
        type: "CREATE",
        taskId: null,
        draft: emptyDraft(sessionId),
        bindings: [],
        bindingsLoading: false,
        bindingsError: null,
        error: null,
      });
    },
    onOpenEdit: (task) => {
      setActionError(null);
      setForm({
        type: "EDIT",
        taskId: task.id,
        draft: taskDraft(task),
        bindings: [],
        bindingsLoading: false,
        bindingsError: null,
        error: null,
      });
    },
    onCloseForm: () => setForm({ type: "CLOSED" }),
    onChangeDraft: (draft) => {
      setForm((current) =>
        current.type === "CLOSED"
          ? current
          : { ...current, draft, error: null },
      );
    },
    onSave: () => {
      if (form.type === "CLOSED") {
        return;
      }
      setActionError(null);
      const result = parseScheduledTaskDraft(form.draft);
      if (!result.success) {
        setForm({ ...form, error: result.error });
        return;
      }
      const values = result.values;
      const common = {
        handle,
        agentId: agent.id,
        title: values.title,
        objective: values.objective,
        at: values.at,
        cron: values.cron,
        timezone: values.timezone,
        channelId: values.channelId,
      };
      if (form.type === "CREATE") {
        createMutation.mutate({ ...common, sessionId });
      } else if (form.taskId !== null) {
        replaceMutation.mutate({ ...common, taskId: form.taskId });
      }
    },
    onRequestCancel: (task) => {
      setActionError(null);
      setCancelTarget(task);
    },
    onCloseCancel: () => setCancelTarget(null),
    onConfirmCancel: () => {
      if (cancelTarget === null) {
        return;
      }
      setActionError(null);
      deleteMutation.mutate({
        handle,
        agentId: agent.id,
        taskId: cancelTarget.id,
      });
    },
  };
}
