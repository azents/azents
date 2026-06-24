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
import { useForm } from "@mantine/form";
import { useState } from "react";
import type { SignupTokenAdminContainerProps } from "../containers/useSignupTokenAdminContainer";
import type { SignupTokenResponse } from "@azents/admin-client";

function SignupTokenCreateForm({
  createState,
  onCreateManualToken,
}: {
  createState: SignupTokenAdminContainerProps["createState"];
  onCreateManualToken: (email: string) => void;
}): React.ReactElement {
  const form = useForm({
    mode: "controlled",
    initialValues: { email: "" },
    validate: {
      email: (value) => (value.trim().includes("@") ? null : "Enter an email."),
    },
  });
  const creating = createState.type === "CREATING";

  function handleSubmit(values: typeof form.values): void {
    onCreateManualToken(values.email.trim());
  }

  return (
    <Paper withBorder p="lg" radius="md">
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="md">
          <Stack gap="xs">
            <Title order={4}>Create signup token</Title>
            <Text size="sm" c="dimmed">
              Create an email-bound token and copy the signup link manually.
            </Text>
          </Stack>
          {createState.type === "IDLE" && createState.error ? (
            <Alert color="red">{createState.error}</Alert>
          ) : null}
          <Group gap="sm" align="flex-end">
            <TextInput
              flex={1}
              label="Email"
              type="email"
              autoComplete="email"
              disabled={creating}
              {...form.getInputProps("email")}
            />
            <Button type="submit" loading={creating} disabled={creating}>
              Create token
            </Button>
          </Group>
        </Stack>
      </form>
    </Paper>
  );
}

function CreatedTokenAlert({
  email,
  signupUrl,
  onClear,
}: {
  email: string;
  signupUrl: string;
  onClear: () => void;
}): React.ReactElement {
  const [copied, setCopied] = useState(false);

  async function copySignupUrl(): Promise<void> {
    await navigator.clipboard.writeText(signupUrl);
    setCopied(true);
  }

  return (
    <Alert color="green" withCloseButton onClose={onClear}>
      <Stack gap="sm">
        <Text fw={600}>Signup link created for {email}</Text>
        <Text size="sm" c="dimmed">
          This link is shown once. Copy it now before leaving the page.
        </Text>
        <Group gap="sm" align="center">
          <Text size="sm" style={{ wordBreak: "break-all" }}>
            {signupUrl}
          </Text>
          <Button
            size="xs"
            variant="light"
            onClick={() => void copySignupUrl()}
          >
            {copied ? "Copied" : "Copy"}
          </Button>
        </Group>
      </Stack>
    </Alert>
  );
}

function tokenStatus(token: SignupTokenResponse): {
  label: string;
  color: string;
} {
  if (token.revoked_at) {
    return { label: "Revoked", color: "red" };
  }
  if (new Date(token.expires_at).getTime() <= Date.now()) {
    return { label: "Expired", color: "gray" };
  }
  if (token.used_count >= token.max_uses) {
    return { label: "Used", color: "yellow" };
  }
  return { label: "Active", color: "green" };
}

function SignupTokenRow({
  token,
  onRevokeToken,
}: {
  token: SignupTokenResponse;
  onRevokeToken: (tokenId: string) => void;
}): React.ReactElement {
  const status = tokenStatus(token);
  const revokable =
    token.revoked_at === null && token.used_count < token.max_uses;

  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{token.email}</Text>
      </Table.Td>
      <Table.Td>
        <Badge color={status.color} variant="light">
          {status.label}
        </Badge>
      </Table.Td>
      <Table.Td>
        <Text size="sm">
          {token.used_count}/{token.max_uses}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {new Date(token.expires_at).toLocaleString()}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {new Date(token.created_at).toLocaleString()}
        </Text>
      </Table.Td>
      <Table.Td>
        <Button
          size="xs"
          variant="subtle"
          color="red"
          disabled={!revokable}
          onClick={() => onRevokeToken(token.id)}
        >
          Revoke
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

function SignupTokenList({
  tokens,
  onRevokeToken,
}: {
  tokens: SignupTokenResponse[];
  onRevokeToken: (tokenId: string) => void;
}): React.ReactElement {
  return (
    <Paper withBorder p="lg" radius="md">
      <Stack gap="md">
        <Title order={4}>Signup tokens</Title>
        {tokens.length === 0 ? (
          <Text size="sm" c="dimmed">
            No signup tokens have been created yet.
          </Text>
        ) : (
          <Table highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Email</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Uses</Table.Th>
                <Table.Th>Expires</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {tokens.map((token) => (
                <SignupTokenRow
                  key={token.id}
                  token={token}
                  onRevokeToken={onRevokeToken}
                />
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Paper>
  );
}

export function SignupTokenAdminView({
  state,
  createState,
  createdToken,
  onCreateManualToken,
  onRevokeToken,
  onClearCreatedToken,
}: SignupTokenAdminContainerProps): React.ReactElement {
  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Stack gap="xs">
          <Title order={2}>Signup tokens</Title>
          <Text c="dimmed">
            Issue email-bound signup links for users who need account access.
          </Text>
        </Stack>
        <SignupTokenCreateForm
          createState={createState}
          onCreateManualToken={onCreateManualToken}
        />
        {createdToken ? (
          <CreatedTokenAlert
            email={createdToken.email}
            signupUrl={createdToken.signupUrl}
            onClear={onClearCreatedToken}
          />
        ) : null}
        {state.type === "LOADING" ? (
          <Center py="xl">
            <Loader />
          </Center>
        ) : state.type === "ERROR" ? (
          <Alert color="red">{state.message}</Alert>
        ) : (
          <SignupTokenList
            tokens={state.tokens}
            onRevokeToken={onRevokeToken}
          />
        )}
      </Stack>
    </Container>
  );
}
