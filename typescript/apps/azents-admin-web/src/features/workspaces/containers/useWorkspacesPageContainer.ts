"use client";

import { useCallback, useState } from "react";
import { serializers, useQueryState } from "@/hooks/use-query-state";
import type { WorkspaceResponse } from "../types";

export interface WorkspacesPageContentProps {
  selectedWorkspaceHandle: string | null;
  isCreateMode: boolean;
  onWorkspaceSelect: (workspace: WorkspaceResponse) => void;
  onCreateNew: () => void;
  onCancel: () => void;
  onSaved: (handle: string) => void;
  onDeleted: () => void;
  onDetailClose: () => void;
}

/**
 * Workspaces 페이지 컨테이너 훅
 *
 * URL 쿼리 상태로 선택된 workspace handle과 생성 모드를 관리합니다.
 */
export function useWorkspacesPageContainer(): WorkspacesPageContentProps {
  const [selectedWorkspaceHandle, setSelectedWorkspaceHandle] = useQueryState(
    "workspace",
    {
      serializer: serializers.stringOrNull(),
    },
  );

  const [isCreateMode, setIsCreateMode] = useState(false);

  const handleWorkspaceSelect = useCallback(
    (workspace: WorkspaceResponse): void => {
      setSelectedWorkspaceHandle(workspace.handle);
      setIsCreateMode(false);
    },
    [setSelectedWorkspaceHandle],
  );

  const handleCreateNew = useCallback((): void => {
    setSelectedWorkspaceHandle(null);
    setIsCreateMode(true);
  }, [setSelectedWorkspaceHandle]);

  const handleCancel = useCallback((): void => {
    setIsCreateMode(false);
  }, []);

  const handleSaved = useCallback(
    (handle: string): void => {
      setSelectedWorkspaceHandle(handle);
      setIsCreateMode(false);
    },
    [setSelectedWorkspaceHandle],
  );

  const handleDeleted = useCallback((): void => {
    setSelectedWorkspaceHandle(null);
    setIsCreateMode(false);
  }, [setSelectedWorkspaceHandle]);

  const handleDetailClose = useCallback((): void => {
    setSelectedWorkspaceHandle(null);
    setIsCreateMode(false);
  }, [setSelectedWorkspaceHandle]);

  return {
    selectedWorkspaceHandle,
    isCreateMode,
    onWorkspaceSelect: handleWorkspaceSelect,
    onCreateNew: handleCreateNew,
    onCancel: handleCancel,
    onSaved: handleSaved,
    onDeleted: handleDeleted,
    onDetailClose: handleDetailClose,
  };
}
