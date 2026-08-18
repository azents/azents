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
import type { VerificationListComponentProps } from "../containers/useVerificationListContainer";
import type {
  EmailVerificationResponse,
  VerificationListState,
} from "../types";

function renderContent(
  state: VerificationListState,
  selectedVerificationId: string | null,
  onRowClick: (verification: EmailVerificationResponse) => void,
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
          <Text c="red">Error: {state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.verifications.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">No verification records found.</Text>
          </Center>
        );
      }
      return (
        <Table highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Email</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Created At</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {state.verifications.map((verification) => (
              <Table.Tr
                key={verification.id}
                onClick={() => onRowClick(verification)}
                style={{ cursor: "pointer" }}
                bg={
                  selectedVerificationId === verification.id
                    ? "var(--mantine-primary-color-light)"
                    : ""
                }
              >
                <Table.Td>
                  <Text size="sm" truncate>
                    {verification.email}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {verification.verified_at ? (
                    <Badge color="green" variant="light" size="sm">
                      Verified
                    </Badge>
                  ) : (
                    <Badge color="gray" variant="light" size="sm">
                      Pending
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="xs" c="dimmed">
                    {new Date(verification.created_at).toLocaleDateString()}
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
 * Verification list view component
 *
 * Renders the appropriate UI for the current ADT state.
 */
export function VerificationListView({
  state,
  selectedVerificationId,
  onRowClick,
}: VerificationListComponentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Group p="md" justify="space-between">
        <Title order={5}>Email Verifications</Title>
      </Group>
      <Box style={{ flex: 1, overflow: "auto" }}>
        {renderContent(state, selectedVerificationId, onRowClick)}
      </Box>
    </Box>
  );
}
