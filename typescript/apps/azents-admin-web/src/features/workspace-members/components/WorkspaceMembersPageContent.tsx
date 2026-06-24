"use client";

import { Box, Select } from "@mantine/core";
import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { trpc } from "@/trpc/client";
import { WorkspaceMemberDetail } from "./WorkspaceMemberDetail";
import { WorkspaceMemberList } from "./WorkspaceMemberList";
import type { WorkspaceMembersPageContentProps } from "../containers/useWorkspaceMembersPageContainer";

/**
 * WorkspaceMembers 페이지 콘텐츠 컴포넌트
 *
 * Workspace 선택 드롭다운 + MasterDetailLayout 반응형 2패널 레이아웃
 */
export function WorkspaceMembersPageContent({
  selectedWorkspaceHandle,
  selectedMemberId,
  onWorkspaceChange,
  onMemberSelect,
  onDeleted,
  onDetailClose,
}: WorkspaceMembersPageContentProps): React.ReactElement {
  const { data: workspacesData } = trpc.workspace.list.useQuery();
  const workspaces = workspacesData?.items ?? [];

  const workspaceOptions = workspaces.map((ws) => ({
    value: ws.handle,
    label: `${ws.name} (${ws.handle})`,
  }));

  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Box
        p="md"
        style={{
          borderBottom: "1px solid var(--mantine-color-default-border)",
        }}
      >
        <Select
          label="Workspace"
          placeholder="Workspace를 선택하세요"
          data={workspaceOptions}
          value={selectedWorkspaceHandle}
          onChange={onWorkspaceChange}
          searchable
          clearable
        />
      </Box>
      <Box style={{ flex: 1, minHeight: 0 }}>
        <MasterDetailLayout
          master={
            <WorkspaceMemberList
              selectedWorkspaceHandle={selectedWorkspaceHandle}
              selectedMemberId={selectedMemberId}
              onRowClick={onMemberSelect}
            />
          }
          detail={
            <WorkspaceMemberDetail
              memberId={selectedMemberId}
              onDeleted={onDeleted}
            />
          }
          detailOpen={selectedMemberId !== null}
          onDetailClose={onDetailClose}
        />
      </Box>
    </Box>
  );
}
