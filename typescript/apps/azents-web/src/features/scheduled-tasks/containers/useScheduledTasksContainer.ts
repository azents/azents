"use client";

import { useCallback, useMemo, useState } from "react";
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
}

export interface ScheduledTasksContainerOutput {
  handle: string;
  agent: AgentResponse;
  state: ScheduledTasksState;
  detail: ScheduledTaskDetailState | null;
  form: ScheduledTaskFormState;
  selectedTaskId: string | null;
  deleteTarget: ScheduledTaskResponse | null;
  mutationBusy: boolean;
  actionError: ScheduledTaskActionError | null;
  creatingSession: boolean;
  onSelectTask: (taskId: string | null) => void;
  onOpenCreate: () => void;
  onOpenEdit: (task: ScheduledTaskResponse) => void;
  onCloseForm: () => void;
  onChangeDraft: (draft: ScheduledTaskDraft) => void;
  onSave: () => void;
  onCreateSession: () => void;
  onRequestDelete: (task: ScheduledTaskResponse) => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
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
}: ScheduledTasksContainerProps): ScheduledTasksContainerOutput {
  const utils = trpc.useUtils();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [form, setForm] = useState<ScheduledTaskFormState>({ type: "CLOSED" });
  const [deleteTarget, setDeleteTarget] =
    useState<ScheduledTaskResponse | null>(null);
  const [actionError, setActionError] =
    useState<ScheduledTaskActionError | null>(null);
  const taskListInput = useMemo(
    () => ({ handle, agentId: agent.id, sessionId: null }),
    [agent.id, handle],
  );
  const teamSessionListInput = useMemo(
    () => ({ agentId: agent.id }),
    [agent.id],
  );

  const tasksQuery = trpc.scheduledTask.list.useQuery(taskListInput, {
    refetchInterval: 5_000,
    staleTime: 0,
  });
  const teamSessionsQuery =
    trpc.scheduledTask.listSelectableTeamSessions.useQuery(
      teamSessionListInput,
    );
  const userSessionsQuery = trpc.chat.listAgentUserSessions.useQuery({
    agentId: agent.id,
  });
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
  const formSessionId = form.type === "CLOSED" ? null : form.draft.sessionId;
  const bindingsQuery = trpc.externalChannel.listSessionChannels.useQuery(
    { handle, agentId: agent.id, sessionId: formSessionId ?? "" },
    { enabled: formSessionId !== null && formSessionId !== "" },
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
      const taskId = deleteTarget?.id;
      setDeleteTarget(null);
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
  const createSessionMutation = trpc.chat.createTeamAgentSession.useMutation({
    onSuccess: async (session) => {
      await Promise.all([
        utils.scheduledTask.listSelectableTeamSessions.invalidate(
          teamSessionListInput,
        ),
        utils.chat.getAgentSessionSidebar.invalidate({ agentId: agent.id }),
      ]);
      setForm((current) =>
        current.type === "CLOSED"
          ? current
          : {
              ...current,
              draft: {
                ...current.draft,
                sessionId: session.id,
                channelId: null,
              },
            },
      );
    },
    onError: (error) =>
      setActionError({ type: "ERROR", message: error.message }),
  });

  const sessions = useMemo(
    () => [
      ...(teamSessionsQuery.data?.items ?? []),
      ...(userSessionsQuery.data?.items ?? []),
    ],
    [teamSessionsQuery.data?.items, userSessionsQuery.data?.items],
  );
  const state: ScheduledTasksState =
    tasksQuery.isPending ||
    teamSessionsQuery.isPending ||
    userSessionsQuery.isPending
      ? { type: "LOADING" }
      : tasksQuery.isError
        ? { type: "ERROR", message: tasksQuery.error.message }
        : teamSessionsQuery.isError
          ? { type: "ERROR", message: teamSessionsQuery.error.message }
          : userSessionsQuery.isError
            ? { type: "ERROR", message: userSessionsQuery.error.message }
            : { type: "LOADED", tasks: tasksQuery.data.items, sessions };
  const detail: ScheduledTaskDetailState | null =
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
            };

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

  return {
    handle,
    agent,
    state,
    detail,
    form: effectiveForm,
    selectedTaskId,
    deleteTarget,
    mutationBusy,
    actionError,
    creatingSession: createSessionMutation.isPending,
    onSelectTask: (taskId) => {
      setActionError(null);
      setSelectedTaskId(taskId);
    },
    onOpenCreate: () => {
      setActionError(null);
      setForm({
        type: "CREATE",
        taskId: null,
        draft: emptyDraft(sessions[0]?.id ?? ""),
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
        createMutation.mutate({ ...common, sessionId: values.sessionId });
      } else if (form.taskId !== null) {
        replaceMutation.mutate({ ...common, taskId: form.taskId });
      }
    },
    onCreateSession: () => {
      setActionError(null);
      createSessionMutation.mutate({
        agentId: agent.id,
        existingProjectPaths: [],
        setupActions: [],
      });
    },
    onRequestDelete: (task) => {
      setActionError(null);
      setDeleteTarget(task);
    },
    onCancelDelete: () => setDeleteTarget(null),
    onConfirmDelete: () => {
      if (deleteTarget === null) {
        return;
      }
      setActionError(null);
      deleteMutation.mutate({
        handle,
        agentId: agent.id,
        taskId: deleteTarget.id,
      });
    },
  };
}
