"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useLocale } from "@/shared/providers/locale";
import type { AgentSessionDirectoryQueryState } from "../agent-session-directory-state";
import type { AgentSessionDirectoryStatus } from "./useAgentSessionDirectoryContainer";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
interface AgentSessionDirectoryProps {
  handle: string;
  agent: AgentResponse;
  status: AgentSessionDirectoryStatus;
  page: number;
  pageSize: number;
  queryState: AgentSessionDirectoryQueryState;
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
export interface AgentSessionDirectoryViewProps {
  agent: AgentSessionDirectoryProps["agent"];
  status: AgentSessionDirectoryProps["status"];
  page: AgentSessionDirectoryProps["page"];
  queryState: AgentSessionDirectoryProps["queryState"];
  actionError: AgentSessionDirectoryProps["actionError"];
  archivingSessionId: AgentSessionDirectoryProps["archivingSessionId"];
  restoringSessionId: AgentSessionDirectoryProps["restoringSessionId"];
  onStatusChange: AgentSessionDirectoryProps["onStatusChange"];
  onPageChange: AgentSessionDirectoryProps["onPageChange"];
  onCreateSession: AgentSessionDirectoryProps["onCreateSession"];
  onRestoreSession: AgentSessionDirectoryProps["onRestoreSession"];
  t: ReturnType<typeof useTranslations<"workspace.agents.detail">>;
  locale: "en-US" | "ko-KR" | "ja-JP" | "fr-FR";
  editingSession: AgentSessionResponse | null;
  editingTitle: string;
  setEditingTitle: React.Dispatch<React.SetStateAction<string>>;
  archiveTarget: AgentSessionResponse | null;
  setArchiveTarget: React.Dispatch<
    React.SetStateAction<AgentSessionResponse | null>
  >;
  basePath: string;
  totalPages: number;
  isArchived: boolean;
  renameBusy: boolean;
  handleCloseRename: () => void;
  handleSubmitRename: () => Promise<void>;
  handleClearTitle: () => Promise<void>;
  handleConfirmArchive: () => void;
  pinningSessionId: AgentSessionDirectoryProps["pinningSessionId"];
  renamingSessionId: AgentSessionDirectoryProps["renamingSessionId"];
  onSetSessionPinned: AgentSessionDirectoryProps["onSetSessionPinned"];
  handleOpenRename: (session: AgentSessionResponse) => void;
}
export function useAgentSessionDirectoryController({
  handle,
  agent,
  status,
  page,
  pageSize,
  queryState,
  actionError,
  renamingSessionId,
  archivingSessionId,
  pinningSessionId,
  restoringSessionId,
  onStatusChange,
  onPageChange,
  onCreateSession,
  onRenameSession,
  onArchiveSession,
  onSetSessionPinned,
  onRestoreSession,
}: AgentSessionDirectoryProps): AgentSessionDirectoryViewProps {
  const t = useTranslations("workspace.agents.detail");
  const { locale } = useLocale();
  const [editingSession, setEditingSession] =
    useState<AgentSessionResponse | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [archiveTarget, setArchiveTarget] =
    useState<AgentSessionResponse | null>(null);
  const basePath = `/w/${handle}/agents/${agent.id}`;
  const totalPages = Math.max(
    1,
    Math.ceil(queryState.snapshot.totalCount / pageSize),
  );
  const isArchived = status === "archived";
  const renameBusy =
    editingSession !== null && renamingSessionId === editingSession.id;

  const handleOpenRename = (session: AgentSessionResponse): void => {
    setEditingSession(session);
    setEditingTitle(session.title ?? "");
  };

  const handleCloseRename = (): void => {
    setEditingSession(null);
    setEditingTitle("");
  };

  const handleSubmitRename = async (): Promise<void> => {
    if (!editingSession || !editingTitle.trim()) {
      return;
    }
    await onRenameSession(editingSession.id, editingTitle.trim());
    handleCloseRename();
  };

  const handleClearTitle = async (): Promise<void> => {
    if (!editingSession) {
      return;
    }
    await onRenameSession(editingSession.id, null);
    handleCloseRename();
  };

  const handleConfirmArchive = (): void => {
    if (!archiveTarget) {
      return;
    }
    onArchiveSession(archiveTarget.id);
    setArchiveTarget(null);
  };
  return {
    agent,
    status,
    page,
    queryState,
    actionError,
    archivingSessionId,
    restoringSessionId,
    onStatusChange,
    onPageChange,
    onCreateSession,
    onRestoreSession,
    t,
    locale,
    editingSession,
    editingTitle,
    setEditingTitle,
    archiveTarget,
    setArchiveTarget,
    basePath,
    totalPages,
    isArchived,
    renameBusy,
    handleCloseRename,
    handleSubmitRename,
    handleClearTitle,
    handleConfirmArchive,
    pinningSessionId,
    renamingSessionId,
    onSetSessionPinned,
    handleOpenRename,
  };
}
