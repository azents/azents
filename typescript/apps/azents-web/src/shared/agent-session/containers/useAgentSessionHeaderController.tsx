"use client";
import { useDocumentTitle } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useAgentFocusedShellMobileNav } from "../AgentFocusedShellMobileNav";
import type { AgentFocusedShellMobileNav } from "../AgentFocusedShellMobileNav";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";
interface AgentSessionHeaderProps {
  agent: AgentResponse;
  session: AgentSessionResponse;
  onUpdateTitle: (title: string | null) => Promise<AgentSessionResponse>;
  onSessionTitleChange?: (session: AgentSessionResponse) => void;
  onTogglePanel: () => void;
  panelOpened: boolean;
  chatControls?: ReactNode;
}
function getSessionDisplayTitle(
  session: AgentSessionResponse,
  t: ReturnType<typeof useTranslations>,
): string {
  const title = session.title?.trim();
  if (title) {
    return title;
  }
  if (session.primary_kind === "team_primary") {
    return t("sessions.primary");
  }
  return t("sessions.session");
}
export interface AgentSessionHeaderViewProps {
  agent: AgentSessionHeaderProps["agent"];
  onTogglePanel: AgentSessionHeaderProps["onTogglePanel"];
  panelOpened: AgentSessionHeaderProps["panelOpened"];
  chatControls: AgentSessionHeaderProps["chatControls"];
  t: ReturnType<typeof useTranslations<"workspace.agents.detail">>;
  tPanel: ReturnType<typeof useTranslations<"chat.sessionPanel">>;
  mobileNav: AgentFocusedShellMobileNav | null;
  session: AgentSessionResponse;
  renameBusy: boolean;
  sessionTitle: string;
  editingOpened: boolean;
  editingTitle: string;
  setEditingTitle: React.Dispatch<React.SetStateAction<string>>;
  handleOpenRename: () => void;
  handleCloseRename: () => void;
  handleSubmitRename: () => Promise<void>;
  handleClearTitle: () => Promise<void>;
}
export function useAgentSessionHeaderController({
  agent,
  session: initialSession,
  onUpdateTitle,
  onSessionTitleChange,
  onTogglePanel,
  panelOpened,
  chatControls,
}: AgentSessionHeaderProps): AgentSessionHeaderViewProps {
  const t = useTranslations("workspace.agents.detail");
  const tPanel = useTranslations("chat.sessionPanel");
  const mobileNav = useAgentFocusedShellMobileNav();
  const [session, setSession] = useState(initialSession);
  const [renameBusy, setRenameBusy] = useState(false);
  useEffect(() => {
    setSession(initialSession);
  }, [initialSession]);
  const sessionTitle = getSessionDisplayTitle(session, t);
  useDocumentTitle(`${sessionTitle} - Azents`);
  const [editingOpened, setEditingOpened] = useState(false);
  const [editingTitle, setEditingTitle] = useState("");

  const handleOpenRename = useCallback((): void => {
    setEditingTitle(session.title ?? "");
    setEditingOpened(true);
  }, [session.title]);

  const handleCloseRename = useCallback((): void => {
    setEditingOpened(false);
    setEditingTitle("");
  }, []);

  const updateSessionTitle = useCallback(
    async (title: string | null): Promise<void> => {
      setRenameBusy(true);
      try {
        const updatedSession = await onUpdateTitle(title);
        setSession(updatedSession);
        onSessionTitleChange?.(updatedSession);
        handleCloseRename();
      } finally {
        setRenameBusy(false);
      }
    },
    [handleCloseRename, onSessionTitleChange, onUpdateTitle],
  );

  const handleSubmitRename = useCallback(async (): Promise<void> => {
    const title = editingTitle.trim();
    if (!title) {
      return;
    }
    await updateSessionTitle(title);
  }, [editingTitle, updateSessionTitle]);

  const handleClearTitle = useCallback(async (): Promise<void> => {
    await updateSessionTitle(null);
  }, [updateSessionTitle]);
  return {
    agent,
    onTogglePanel,
    panelOpened,
    chatControls,
    t,
    tPanel,
    mobileNav,
    session,
    renameBusy,
    sessionTitle,
    editingOpened,
    editingTitle,
    setEditingTitle,
    handleOpenRename,
    handleCloseRename,
    handleSubmitRename,
    handleClearTitle,
  };
}
