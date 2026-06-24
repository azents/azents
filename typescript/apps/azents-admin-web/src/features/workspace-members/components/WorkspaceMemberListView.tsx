"use client";

import {
  Badge,
  Box,
  Center,
  Group,
  Loader,
  Table,
  Text,
  Title,
} from "@mantine/core";
import dayjs from "dayjs";
import type { WorkspaceMemberListComponentProps } from "../containers/useWorkspaceMemberListContainer";
import type { WorkspaceMemberListState, WorkspaceUserResponse } from "../types";

function renderContent(
  state: WorkspaceMemberListState,
  selectedMemberId: string | null,
  onRowClick: (member: WorkspaceUserResponse) => void,
): React.ReactElement {
  switch (state.type) {
    case "NO_WORKSPACE":
      return (
        <Center p="xl">
          <Text c="dimmed">Workspace를 선택하세요.</Text>
        </Center>
      );
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
      if (state.members.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">등록된 멤버가 없습니다.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>이름</Table.Th>
              <Table.Th>역할</Table.Th>
              <Table.Th>가입일</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {state.members.map((member) => (
              <Table.Tr
                key={member.id}
                onClick={() => onRowClick(member)}
                style={{ cursor: "pointer" }}
                bg={
                  selectedMemberId === member.id
                    ? "var(--mantine-primary-color-light)"
                    : ""
                }
              >
                <Table.Td>{member.name}</Table.Td>
                <Table.Td>
                  <Badge variant="light" size="sm">
                    {member.role}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">
                    {dayjs(member.created_at).format("YYYY-MM-DD")}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      );
  }
}

/**
 * WorkspaceMember 목록 뷰 컴포넌트
 *
 * ADT 상태에 따라 적절한 UI를 렌더링합니다.
 */
export function WorkspaceMemberListView({
  state,
  selectedMemberId,
  onRowClick,
}: WorkspaceMemberListComponentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Group p="md" justify="space-between">
        <Title order={5}>Workspace Members</Title>
      </Group>
      <Box style={{ flex: 1, overflow: "auto" }}>
        {renderContent(state, selectedMemberId, onRowClick)}
      </Box>
    </Box>
  );
}
