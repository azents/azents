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
          <Text c="dimmed">Select a workspace.</Text>
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
          <Text c="red">Error: {state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.members.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">No workspace members found.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th>Joined At</Table.Th>
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
 * Workspace member list view component
 *
 * Renders the appropriate UI for the current ADT state.
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
