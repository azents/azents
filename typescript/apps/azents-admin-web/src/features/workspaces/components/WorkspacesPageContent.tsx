"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { WorkspaceDetail } from "./WorkspaceDetail";
import { WorkspaceList } from "./WorkspaceList";
import type { WorkspacesPageContentProps } from "../containers/useWorkspacesPageContainer";

/**
 * Workspaces 페이지 콘텐츠 컴포넌트
 *
 * MasterDetailLayout을 사용한 반응형 2패널 레이아웃
 */
export function WorkspacesPageContent({
  selectedWorkspaceHandle,
  isCreateMode,
  onWorkspaceSelect,
  onCreateNew,
  onCancel,
  onSaved,
  onDeleted,
  onDetailClose,
}: WorkspacesPageContentProps): React.ReactElement {
  return (
    <MasterDetailLayout
      master={
        <WorkspaceList
          selectedWorkspaceHandle={selectedWorkspaceHandle}
          onRowClick={onWorkspaceSelect}
          onCreateNew={onCreateNew}
        />
      }
      detail={
        <WorkspaceDetail
          workspaceHandle={selectedWorkspaceHandle}
          isCreateMode={isCreateMode}
          onSaved={onSaved}
          onDeleted={onDeleted}
          onCancel={onCancel}
        />
      }
      detailOpen={selectedWorkspaceHandle !== null || isCreateMode}
      onDetailClose={onDetailClose}
    />
  );
}
