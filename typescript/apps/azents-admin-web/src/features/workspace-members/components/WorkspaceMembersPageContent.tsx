"use client";

import { Alert, Box, Select } from "@mantine/core";
import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { WorkspaceMemberDetail } from "./WorkspaceMemberDetail";
import { WorkspaceMemberList } from "./WorkspaceMemberList";
import type { WorkspaceMembersPageContentProps } from "../containers/useWorkspaceMembersPageContainer";

/** Workspace selector and responsive member-management master-detail layout. */
export function WorkspaceMembersPageContent({
  workspaceSelectorState,
  selectedWorkspaceHandle,
  selectedMemberId,
  isCreateMode,
  onWorkspaceChange,
  onMemberSelect,
  onCreateNew,
  onSaved,
  onDeleted,
  onCancel,
  onDetailClose,
}: WorkspaceMembersPageContentProps): React.ReactElement {
  const workspaceOptions =
    workspaceSelectorState.type === "READY"
      ? workspaceSelectorState.options
      : [];

  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Box
        p="md"
        style={{
          borderBottom: "1px solid var(--mantine-color-default-border)",
        }}
      >
        {workspaceSelectorState.type === "ERROR" && (
          <Alert color="red" mb="sm" title="Unable to load Workspaces">
            {workspaceSelectorState.message}
          </Alert>
        )}
        <Select
          label="Workspace"
          description="Choose the Workspace whose membership you want to manage."
          placeholder="Select a workspace"
          data={workspaceOptions}
          value={selectedWorkspaceHandle}
          onChange={onWorkspaceChange}
          searchable
          clearable
          disabled={workspaceSelectorState.type === "LOADING"}
        />
      </Box>
      <Box style={{ flex: 1, minHeight: 0 }}>
        <MasterDetailLayout
          master={
            <WorkspaceMemberList
              selectedWorkspaceHandle={selectedWorkspaceHandle}
              selectedMemberId={selectedMemberId}
              onRowClick={onMemberSelect}
              onCreateNew={onCreateNew}
            />
          }
          detail={
            <WorkspaceMemberDetail
              workspaceHandle={selectedWorkspaceHandle}
              memberId={selectedMemberId}
              isCreateMode={isCreateMode}
              onSaved={onSaved}
              onDeleted={onDeleted}
              onCancel={onCancel}
            />
          }
          detailOpen={selectedMemberId !== null || isCreateMode}
          onDetailClose={onDetailClose}
        />
      </Box>
    </Box>
  );
}
