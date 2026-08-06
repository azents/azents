"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

export const AGENT_SESSION_DIRECTORY_PAGE_SIZE = 25;

export type AgentSessionDirectoryStatus = "active" | "archived";

export interface AgentSessionDirectoryContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentSessionDirectoryContainerOutput {
  handle: string;
  agent: AgentResponse;
  status: AgentSessionDirectoryStatus;
  page: number;
  pageSize: number;
  sessions: AgentSessionResponse[];
  totalCount: number;
  currentArchiveRetentionDays: number | null;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  renamingSessionId: string | null;
  archivingSessionId: string | null;
  pinningSessionId: string | null;
  restoringSessionId: string | null;
  onStatusChange: (status: AgentSessionDirectoryStatus) => void;
  onPageChange: (page: number) => void;
  onCreateSession: () => void;
  onRenameSession: (sessionId: string, title: string | null) => Promise<void>;
  onArchiveSession: (sessionId: string) => void;
  onSetSessionPinned: (sessionId: string, pinned: boolean) => void;
  onRestoreSession: (sessionId: string) => void;
}

function parseStatus(value: string | null): AgentSessionDirectoryStatus {
  return value === "archived" ? "archived" : "active";
}

function parsePage(value: string | null): number {
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 1) {
    return 1;
  }
  return parsed;
}

export function useAgentSessionDirectoryContainer({
  handle,
  agent,
}: AgentSessionDirectoryContainerProps): AgentSessionDirectoryContainerOutput {
  const router = useRouter();
  const searchParams = useSearchParams();
  const utils = trpc.useUtils();
  const status = parseStatus(searchParams.get("status"));
  const page = parsePage(searchParams.get("page"));
  const offset = (page - 1) * AGENT_SESSION_DIRECTORY_PAGE_SIZE;
  const directoryQuery = trpc.chat.listAgentSessions.useQuery({
    agentId: agent.id,
    status,
    offset,
    limit: AGENT_SESSION_DIRECTORY_PAGE_SIZE,
  });

  const basePath = `/w/${handle}/agents/${agent.id}`;
  const replaceDirectoryQuery = useCallback(
    (nextStatus: AgentSessionDirectoryStatus, nextPage: number): void => {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.set("status", nextStatus);
      nextParams.set("page", String(nextPage));
      router.replace(`${basePath}/sessions?${nextParams.toString()}`);
    },
    [basePath, router, searchParams],
  );

  const totalCount = directoryQuery.data?.total_count ?? 0;
  const totalPages = Math.max(
    1,
    Math.ceil(totalCount / AGENT_SESSION_DIRECTORY_PAGE_SIZE),
  );

  useEffect((): void => {
    if (!directoryQuery.data || page <= totalPages) {
      return;
    }
    replaceDirectoryQuery(status, totalPages);
  }, [directoryQuery.data, page, replaceDirectoryQuery, status, totalPages]);

  const refreshSessionReads = useCallback((): void => {
    void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
    void utils.chat.getAgentSessionSidebar.invalidate({ agentId: agent.id });
  }, [
    agent.id,
    utils.chat.getAgentSessionSidebar,
    utils.chat.listAgentSessions,
  ]);

  const updateTitleMutation = trpc.chat.updateAgentSessionTitle.useMutation();
  const updatePinMutation = trpc.chat.updateAgentSessionPin.useMutation();
  const archiveSessionMutation = trpc.chat.archiveAgentSession.useMutation();
  const restoreSessionMutation = trpc.chat.restoreAgentSession.useMutation();

  const onStatusChange = useCallback(
    (nextStatus: AgentSessionDirectoryStatus): void => {
      replaceDirectoryQuery(nextStatus, 1);
    },
    [replaceDirectoryQuery],
  );

  const onPageChange = useCallback(
    (nextPage: number): void => {
      replaceDirectoryQuery(status, Math.max(1, nextPage));
    },
    [replaceDirectoryQuery, status],
  );

  const onCreateSession = useCallback((): void => {
    router.push(`${basePath}/sessions/new`);
  }, [basePath, router]);

  const onRenameSession = useCallback(
    async (sessionId: string, title: string | null): Promise<void> => {
      await updateTitleMutation.mutateAsync({
        agentId: agent.id,
        sessionId,
        title,
      });
      refreshSessionReads();
      void utils.chat.getAgentSession.invalidate({
        agentId: agent.id,
        sessionId,
      });
    },
    [
      agent.id,
      refreshSessionReads,
      updateTitleMutation,
      utils.chat.getAgentSession,
    ],
  );

  const onArchiveSession = useCallback(
    (sessionId: string): void => {
      archiveSessionMutation.reset();
      archiveSessionMutation.mutate(
        { agentId: agent.id, sessionId },
        { onSuccess: refreshSessionReads },
      );
    },
    [agent.id, archiveSessionMutation, refreshSessionReads],
  );

  const onSetSessionPinned = useCallback(
    (sessionId: string, pinned: boolean): void => {
      updatePinMutation.reset();
      updatePinMutation.mutate(
        { agentId: agent.id, sessionId, pinned },
        { onSuccess: refreshSessionReads },
      );
    },
    [agent.id, refreshSessionReads, updatePinMutation],
  );

  const onRestoreSession = useCallback(
    (sessionId: string): void => {
      restoreSessionMutation.reset();
      restoreSessionMutation.mutate(
        { agentId: agent.id, sessionId },
        { onSuccess: refreshSessionReads },
      );
    },
    [agent.id, refreshSessionReads, restoreSessionMutation],
  );

  const actionError = useMemo(
    () =>
      updateTitleMutation.error?.message ??
      updatePinMutation.error?.message ??
      archiveSessionMutation.error?.message ??
      restoreSessionMutation.error?.message ??
      null,
    [
      archiveSessionMutation.error?.message,
      restoreSessionMutation.error?.message,
      updatePinMutation.error?.message,
      updateTitleMutation.error?.message,
    ],
  );

  return {
    handle,
    agent,
    status,
    page,
    pageSize: AGENT_SESSION_DIRECTORY_PAGE_SIZE,
    sessions: directoryQuery.data?.items ?? [],
    totalCount,
    currentArchiveRetentionDays:
      directoryQuery.data?.current_archive_retention_days ?? null,
    loading: directoryQuery.isPending,
    error: directoryQuery.error?.message ?? null,
    actionError,
    renamingSessionId: updateTitleMutation.isPending
      ? updateTitleMutation.variables.sessionId
      : null,
    archivingSessionId: archiveSessionMutation.isPending
      ? archiveSessionMutation.variables.sessionId
      : null,
    pinningSessionId: updatePinMutation.isPending
      ? updatePinMutation.variables.sessionId
      : null,
    restoringSessionId: restoreSessionMutation.isPending
      ? restoreSessionMutation.variables.sessionId
      : null,
    onStatusChange,
    onPageChange,
    onCreateSession,
    onRenameSession,
    onArchiveSession,
    onSetSessionPinned,
    onRestoreSession,
  };
}
