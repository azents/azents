"use client";

import { useDisclosure } from "@mantine/hooks";
import { useCallback, useState } from "react";
import type { AgentListContainerOutput } from "./useAgentListContainer";

export interface AgentListViewProps extends AgentListContainerOutput {
  deleteOpened: boolean;
  closeDelete: () => void;
  handleDeleteClick: (agentId: string) => void;
  handleDeleteConfirm: () => void;
}

export function useAgentListController(
  props: AgentListContainerOutput,
): AgentListViewProps {
  const { onDelete } = props;
  const [deleteOpened, { open: openDelete, close: closeDelete }] =
    useDisclosure(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const handleDeleteClick = useCallback(
    (agentId: string): void => {
      setDeleteTarget(agentId);
      openDelete();
    },
    [openDelete],
  );
  const handleDeleteConfirm = useCallback((): void => {
    if (deleteTarget) {
      onDelete(deleteTarget);
      setDeleteTarget(null);
      closeDelete();
    }
  }, [deleteTarget, onDelete, closeDelete]);
  return {
    ...props,
    deleteOpened,
    closeDelete,
    handleDeleteClick,
    handleDeleteConfirm,
  };
}
