"use client";

import {
  Badge,
  Box,
  Button,
  Center,
  Group,
  Loader,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconPlus } from "@tabler/icons-react";
import type { WorkspaceListComponentProps } from "../containers/useWorkspaceListContainer";
import type { WorkspaceListState, WorkspaceResponse } from "../types";

function renderContent(
  state: WorkspaceListState,
  selectedWorkspaceHandle: string | null,
  onRowClick: (workspace: WorkspaceResponse) => void,
): React.ReactElement {
  switch (state.type) {
    case "LOADING":
      return (
        <Center p="xl">
          <Loader />
        </Center>
      );
    case "ERROR":
      return (
        <Center p="xl">
          <Text c="red">에러: {state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.workspaces.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">등록된 Workspace가 없습니다.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Handle</Table.Th>
              <Table.Th>이름</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {state.workspaces.map((workspace) => (
              <Table.Tr
                key={workspace.handle}
                onClick={() => onRowClick(workspace)}
                style={{ cursor: "pointer" }}
                bg={
                  selectedWorkspaceHandle === workspace.handle
                    ? "var(--mantine-primary-color-light)"
                    : ""
                }
              >
                <Table.Td>
                  <Badge variant="light">{workspace.handle}</Badge>
                </Table.Td>
                <Table.Td>{workspace.name}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
  }
}

/**
 * Workspace 목록 뷰 컴포넌트
 *
 * ADT 상태에 따라 적절한 UI를 렌더링합니다.
 */
export function WorkspaceListView({
  state,
  selectedWorkspaceHandle,
  onRowClick,
  onCreateNew,
}: WorkspaceListComponentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Group p="md" justify="space-between">
        <Title order={5}>Workspaces</Title>
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          onClick={onCreateNew}
        >
          Workspace 추가
        </Button>
      </Group>
      <Box style={{ flex: 1, overflow: "auto" }}>
        {renderContent(state, selectedWorkspaceHandle, onRowClick)}
      </Box>
    </Box>
  );
}
