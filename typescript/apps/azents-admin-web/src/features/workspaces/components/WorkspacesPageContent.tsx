"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { WorkspaceDetail } from "./WorkspaceDetail";
import { WorkspaceList } from "./WorkspaceList";
import type { WorkspacesPageContentProps } from "../containers/useWorkspacesPageContainer";

/**
 * Workspaces page content component
 *
 * Responsive two-panel layout using MasterDetailLayout
 */
export function WorkspacesPageContent({
  selectedWorkspaceHandle,
  isCreateMode,
  onWorkspaceSelect,
  onCreateNew,
  onCancel,
  onSaved,
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
          onCancel={onCancel}
        />
      }
      detailOpen={selectedWorkspaceHandle !== null || isCreateMode}
      onDetailClose={onDetailClose}
    />
  );
}
