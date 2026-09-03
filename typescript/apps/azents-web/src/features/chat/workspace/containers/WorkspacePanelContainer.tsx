"use client";

import { Text } from "@mantine/core";
import { useModals } from "@mantine/modals";
import { WorkspacePanel } from "../components/WorkspacePanel";
import { useWorkspacePanelTranslations } from "./useWorkspacePanelTranslations";
import type { WorkspacePanelProps } from "../components/WorkspacePanel";
import type { WorkspaceEntry } from "../types";

export function WorkspacePanelContainer(
  props: WorkspacePanelProps,
): React.ReactElement {
  const t = useWorkspacePanelTranslations();
  const modals = useModals();

  const openDeleteConfirm = (entry: WorkspaceEntry): void => {
    modals.openConfirmModal({
      title: t("deleteConfirmTitle"),
      children: (
        <Text size="sm">{t("deleteConfirm", { path: entry.path })}</Text>
      ),
      labels: { confirm: t("delete"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () =>
        props.onDeletePath(entry.path, entry.kind === "directory"),
    });
  };

  const openRemoveProjectConfirm = (entry: WorkspaceEntry): void => {
    modals.openConfirmModal({
      title: t("deleteProjectConfirmTitle"),
      children: (
        <Text size="sm">
          {t("deleteProjectConfirmDescription", { path: entry.path })}
        </Text>
      ),
      labels: { confirm: t("deleteProject"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => props.onRemoveProjectEntry(entry),
    });
  };

  const openDeleteWorktreeProjectConfirm = (entry: WorkspaceEntry): void => {
    modals.openConfirmModal({
      title: t("deleteWorktreeConfirmTitle"),
      children: (
        <Text size="sm">
          {t("deleteWorktreeConfirmDescription", { path: entry.path })}
        </Text>
      ),
      labels: { confirm: t("deleteWorktree"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => props.onDeleteWorktreeProjectEntry(entry),
    });
  };

  const openBulkDeleteConfirm = (count: number): void => {
    modals.openConfirmModal({
      title: t("bulkDeleteConfirmTitle"),
      children: <Text size="sm">{t("bulkDeleteConfirm", { count })}</Text>,
      labels: { confirm: t("delete"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => props.onBulkDeletePaths(true),
    });
  };

  const requestCreateDirectory = (basePath: string): void => {
    const name = window.prompt(t("newFolderPrompt"));
    if (name?.trim()) {
      props.onCreateDirectory(`${basePath}/${name.trim()}`);
    }
  };

  const requestRenamePath = (entry: WorkspaceEntry): void => {
    const name = window.prompt(t("renamePrompt"), entry.name);
    if (name?.trim() && name.trim() !== entry.name) {
      props.onRenamePath(entry.path, name.trim());
    }
  };

  const requestMovePath = (entry: WorkspaceEntry): void => {
    const destination = window.prompt(t("movePrompt"), entry.path);
    if (destination?.trim() && destination.trim() !== entry.path) {
      props.onMovePath(entry.path, destination.trim());
    }
  };

  const requestBulkMove = (basePath: string): void => {
    const destination = window.prompt(t("movePrompt"), basePath);
    if (destination?.trim()) {
      props.onBulkMovePaths(destination.trim());
    }
  };

  return (
    <WorkspacePanel
      {...props}
      t={t}
      onRequestBulkDelete={openBulkDeleteConfirm}
      onRequestBulkMove={requestBulkMove}
      onRequestCreateDirectory={requestCreateDirectory}
      onRequestDeletePath={openDeleteConfirm}
      onRequestDeleteWorktreeProject={openDeleteWorktreeProjectConfirm}
      onRequestMovePath={requestMovePath}
      onRequestRemoveProject={openRemoveProjectConfirm}
      onRequestRenamePath={requestRenamePath}
    />
  );
}
