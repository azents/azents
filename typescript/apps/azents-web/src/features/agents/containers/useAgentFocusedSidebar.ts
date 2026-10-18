"use client";

import { useMantineColorScheme } from "@mantine/core";
import { usePathname } from "next/navigation";
import { useCallback, useState } from "react";
import { useColorMode } from "@/shared/providers/color-mode";
import { useLocale } from "@/shared/providers/locale";
import type { AgentFocusedSidebarProps } from "../components/AgentFocusedSidebar";
import type { ColorModePreference } from "@/shared/lib/color-mode";
import type { SupportedLocale } from "@/shared/lib/locale";
import type { AgentSessionResponse } from "@azents/public-client";
import type { Dispatch, SetStateAction } from "react";

export interface AgentFocusedSidebarViewProps extends AgentFocusedSidebarProps {
  pathname: string;
  mode: "light" | "dark";
  preference: ColorModePreference;
  locale: SupportedLocale;
  editingSession: AgentSessionResponse | null;
  editingTitle: string;
  setEditingTitle: Dispatch<SetStateAction<string>>;
  archiveTarget: AgentSessionResponse | null;
  setArchiveTarget: Dispatch<SetStateAction<AgentSessionResponse | null>>;
  handleSelectColorMode: (preference: ColorModePreference) => void;
  handleLogout: () => void;
  handleOpenRename: (session: AgentSessionResponse) => void;
  handleCloseRename: () => void;
  handleSubmitRename: () => Promise<void>;
  handleClearTitle: () => Promise<void>;
  handleConfirmArchive: () => void;
}

export function useAgentFocusedSidebar(
  props: AgentFocusedSidebarProps,
): AgentFocusedSidebarViewProps {
  const { onLogout, onRenameSession, onArchiveSession } = props;
  const pathname = usePathname();
  const { mode, preference, setColorMode } = useColorMode();
  const { locale } = useLocale();
  const { setColorScheme } = useMantineColorScheme();
  const [editingSession, setEditingSession] =
    useState<AgentSessionResponse | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [archiveTarget, setArchiveTarget] =
    useState<AgentSessionResponse | null>(null);
  const handleSelectColorMode = useCallback(
    (value: ColorModePreference): void => {
      setColorMode(value);
      setColorScheme(value === "system" ? "auto" : value);
    },
    [setColorMode, setColorScheme],
  );
  const handleLogout = useCallback((): void => {
    onLogout();
  }, [onLogout]);
  const handleOpenRename = useCallback(
    (session: AgentSessionResponse): void => {
      setEditingSession(session);
      setEditingTitle(session.title ?? "");
    },
    [],
  );
  const handleCloseRename = useCallback((): void => {
    setEditingSession(null);
    setEditingTitle("");
  }, []);
  const handleSubmitRename = useCallback(async (): Promise<void> => {
    if (!editingSession || !onRenameSession) {
      return;
    }
    await onRenameSession(editingSession.id, editingTitle.trim());
    handleCloseRename();
  }, [editingSession, editingTitle, handleCloseRename, onRenameSession]);
  const handleClearTitle = useCallback(async (): Promise<void> => {
    if (!editingSession || !onRenameSession) {
      return;
    }
    await onRenameSession(editingSession.id, null);
    handleCloseRename();
  }, [editingSession, handleCloseRename, onRenameSession]);
  const handleConfirmArchive = useCallback((): void => {
    if (archiveTarget === null) {
      return;
    }
    onArchiveSession?.(archiveTarget.id);
    setArchiveTarget(null);
  }, [archiveTarget, onArchiveSession]);
  return {
    ...props,
    pathname,
    mode,
    preference,
    locale,
    editingSession,
    editingTitle,
    setEditingTitle,
    archiveTarget,
    setArchiveTarget,
    handleSelectColorMode,
    handleLogout,
    handleOpenRename,
    handleCloseRename,
    handleSubmitRename,
    handleClearTitle,
    handleConfirmArchive,
  };
}
