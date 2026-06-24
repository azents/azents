"use client";

import {
  Alert,
  Badge,
  Button,
  Center,
  Container,
  Group,
  Loader,
  Paper,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import type { PasswordResetAdminContainerProps } from "../containers/usePasswordResetAdminContainer";

export function PasswordResetAdminView({
  state,
  email,
  created,
  creating,
  onEmailChange,
  onCreate,
  onRevoke,
}: PasswordResetAdminContainerProps): React.ReactElement {
  if (state.type === "LOADING") {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Center py="xl">
        <Text c="red">{state.message}</Text>
      </Center>
    );
  }

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <div>
          <Title order={2}>Password reset links</Title>
          <Text c="dimmed" size="sm">
            Create one-time reset links for users who cannot sign in.
          </Text>
        </div>

        <Paper withBorder p="lg" radius="md">
          <Stack gap="md">
            <TextInput
              label="User email"
              value={email}
              onChange={(event) => onEmailChange(event.currentTarget.value)}
              placeholder="user@example.com"
            />
            <Button onClick={onCreate} loading={creating} disabled={!email}>
              Create reset link
            </Button>
            {created ? (
              <Alert color="green" title="Reset link created">
                <Stack gap="xs">
                  <Text size="sm">
                    Copy this link now. It will not be shown again.
                  </Text>
                  <Text size="sm" ff="monospace">
                    {created.reset_url}
                  </Text>
                </Stack>
              </Alert>
            ) : null}
          </Stack>
        </Paper>

        <Paper withBorder p="lg" radius="md">
          <Title order={4} mb="md">
            Existing reset links
          </Title>
          <Table.ScrollContainer minWidth={700}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>ID</Table.Th>
                  <Table.Th>User</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Expires</Table.Th>
                  <Table.Th>Actions</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {state.items.map((item) => {
                  const status = item.revoked_at
                    ? "revoked"
                    : item.used_at
                      ? "used"
                      : "active";
                  return (
                    <Table.Tr key={item.id}>
                      <Table.Td>{item.id}</Table.Td>
                      <Table.Td>{item.user_id}</Table.Td>
                      <Table.Td>
                        <Badge>{status}</Badge>
                      </Table.Td>
                      <Table.Td>
                        {new Date(item.expires_at).toLocaleString()}
                      </Table.Td>
                      <Table.Td>
                        <Group gap="xs">
                          <Button
                            size="xs"
                            variant="light"
                            disabled={status !== "active"}
                            onClick={() => onRevoke(item.id)}
                          >
                            Revoke
                          </Button>
                        </Group>
                      </Table.Td>
                    </Table.Tr>
                  );
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      </Stack>
    </Container>
  );
}
