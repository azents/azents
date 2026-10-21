"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type {
  ProjectDirectoryPickerEntry,
  ProjectDirectoryPickerState,
} from "../types";
interface AgentWorkspaceDirectoryPickerModalProps {
  opened: boolean;
  state: ProjectDirectoryPickerState;
  onClose: () => void;
  onOpenDirectory: (path: string) => void;
  onSelectDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefresh: () => void;
  onStartRuntime: () => void;
  onRestartRuntime: () => void;
  runtimeSettingsHref?: string;
  translationNamespace?: "chat" | "agentWorkspacePicker";
}

export interface AgentWorkspaceDirectoryPickerModalViewProps {
  opened: AgentWorkspaceDirectoryPickerModalProps["opened"];
  state: AgentWorkspaceDirectoryPickerModalProps["state"];
  onClose: AgentWorkspaceDirectoryPickerModalProps["onClose"];
  onOpenDirectory: AgentWorkspaceDirectoryPickerModalProps["onOpenDirectory"];
  onSelectDirectory: AgentWorkspaceDirectoryPickerModalProps["onSelectDirectory"];
  onRefresh: AgentWorkspaceDirectoryPickerModalProps["onRefresh"];
  onStartRuntime: AgentWorkspaceDirectoryPickerModalProps["onStartRuntime"];
  onRestartRuntime: AgentWorkspaceDirectoryPickerModalProps["onRestartRuntime"];
  runtimeSettingsHref?: AgentWorkspaceDirectoryPickerModalProps["runtimeSettingsHref"];
  t: ReturnType<typeof useTranslations<"chat" | "agentWorkspacePicker">>;
  restartConfirmOpen: boolean;
  setRestartConfirmOpen: React.Dispatch<React.SetStateAction<boolean>>;
  closePicker: () => void;
}
export function useAgentWorkspaceDirectoryPickerModalController({
  opened,
  state,
  onClose,
  onOpenDirectory,
  onSelectDirectory,
  onRefresh,
  onStartRuntime,
  onRestartRuntime,
  runtimeSettingsHref,
  translationNamespace = "agentWorkspacePicker",
}: AgentWorkspaceDirectoryPickerModalProps): AgentWorkspaceDirectoryPickerModalViewProps {
  const t = useTranslations(translationNamespace);
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);

  const closePicker = (): void => {
    setRestartConfirmOpen(false);
    onClose();
  };

  return {
    opened,
    state,
    onClose,
    onOpenDirectory,
    onSelectDirectory,
    onRefresh,
    onStartRuntime,
    onRestartRuntime,
    runtimeSettingsHref,
    t,
    restartConfirmOpen,
    setRestartConfirmOpen,
    closePicker,
  };
}
