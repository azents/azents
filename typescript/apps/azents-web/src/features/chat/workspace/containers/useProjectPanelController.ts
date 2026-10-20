"use client";

import { useState } from "react";
import type { ProjectPanelProps } from "../components/ProjectPanel";

export interface ProjectPanelViewProps extends ProjectPanelProps {
  deleteProjectId: string | null;
  setDeleteProjectId: (id: string | null) => void;
  handleConfirmDeleteProject: () => void;
}

export function useProjectPanelController(
  props: ProjectPanelProps,
): ProjectPanelViewProps {
  const [deleteProjectId, setDeleteProjectId] = useState<string | null>(null);
  const handleConfirmDeleteProject = (): void => {
    if (!deleteProjectId) {
      return;
    }
    props.onDeleteProject(deleteProjectId);
    setDeleteProjectId(null);
  };
  return {
    ...props,
    deleteProjectId,
    setDeleteProjectId,
    handleConfirmDeleteProject,
  };
}
