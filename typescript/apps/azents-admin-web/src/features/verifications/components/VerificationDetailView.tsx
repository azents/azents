"use client";

import {
  Badge,
  Box,
  Center,
  Loader,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import type { VerificationDetailComponentProps } from "../containers/useVerificationDetailContainer";

/**
 * Date and time formatting helper
 */
function formatDateTime(isoString: string): string {
  return new Date(isoString).toLocaleString();
}

/**
 * Verification detail view component
 *
 * Renders the appropriate UI for the current ADT state.
 * Read-only; no form is provided.
 */
export function VerificationDetailView({
  state,
}: VerificationDetailComponentProps): React.ReactElement {
  switch (state.type) {
    case "EMPTY":
      return (
        <Center h="100%">
          <Text c="dimmed">Select a verification record.</Text>
        </Center>
      );
    case "LOADING":
      return (
        <Center h="100%">
          <Loader />
        </Center>
      );
    case "ERROR":
      return (
        <Center h="100%">
          <Text c="red">Error: {state.message}</Text>
        </Center>
      );
    case "LOADED": {
      const v = state.verification;
      return (
        <Box p="md">
          <Stack gap="md">
            <Title order={5}>Verification Details</Title>
            <Table>
              <Table.Tbody>
                <Table.Tr>
                  <Table.Th w={120}>ID</Table.Th>
                  <Table.Td>
                    <Text size="sm" ff="monospace">
                      {v.id}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Email</Table.Th>
                  <Table.Td>{v.email}</Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Verification Code</Table.Th>
                  <Table.Td>
                    <Text ff="monospace" fw={600}>
                      {v.code}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>CSRF Token</Table.Th>
                  <Table.Td>
                    <Text size="xs" ff="monospace" truncate>
                      {v.csrf_token}
                    </Text>
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Status</Table.Th>
                  <Table.Td>
                    {v.verified_at ? (
                      <Badge color="green" variant="light">
                        Verified
                      </Badge>
                    ) : (
                      <Badge color="gray" variant="light">
                        Pending
                      </Badge>
                    )}
                  </Table.Td>
                </Table.Tr>
                <Table.Tr>
                  <Table.Th>Expires At</Table.Th>
                  <Table.Td>{formatDateTime(v.expires_at)}</Table.Td>
                </Table.Tr>
                {v.verified_at ? (
                  <Table.Tr>
                    <Table.Th>Verified At</Table.Th>
                    <Table.Td>{formatDateTime(v.verified_at)}</Table.Td>
                  </Table.Tr>
                ) : null}
                <Table.Tr>
                  <Table.Th>Created At</Table.Th>
                  <Table.Td>{formatDateTime(v.created_at)}</Table.Td>
                </Table.Tr>
              </Table.Tbody>
            </Table>
          </Stack>
        </Box>
      );
    }
  }
}
