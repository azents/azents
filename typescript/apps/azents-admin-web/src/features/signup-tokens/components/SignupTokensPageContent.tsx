"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
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
import { IconCopy, IconLinkPlus, IconTrash } from "@tabler/icons-react";
import dayjs from "dayjs";
import type { SignupTokensPageContentProps } from "../containers/useSignupTokensPageContainer";
import type { SignupTokenListState } from "../types";
import type { SignupTokenResponse } from "@azents/admin-client";

function SignupTokenCreateForm({
  createState,
  onCreateToken,
}: {
  createState: SignupTokensPageContentProps["createState"];
  onCreateToken: (email: string) => void;
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
    onCreateToken(values.email.trim());
  }

  return (
    <Paper withBorder p="md">
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="md">
          <Group justify="space-between" align="flex-start">
            <Stack gap={4}>
              <Title order={5}>Create signup link</Title>
              <Text size="sm" c="dimmed">
                Create a one-time email-bound signup link.
              </Text>
            </Stack>
            <Button
              type="submit"
              leftSection={<IconLinkPlus size={16} />}
              loading={creating}
              disabled={creating}
            >
              Create
            </Button>
          </Group>
          {createState.type === "IDLE" && createState.error ? (
            <Alert color="red">{createState.error}</Alert>
          ) : null}
          <TextInput
            label="Email"
            type="email"
            autoComplete="email"
            disabled={creating}
            {...form.getInputProps("email")}
          />
        </Stack>
      </form>
    </Paper>
  );
}

function CreatedTokenAlert({
  email,
  signupUrl,
  copied,
  onCopy,
  onClear,
}: {
  email: string;
  signupUrl: string;
  copied: boolean;
  onCopy: () => void;
  onClear: () => void;
}): React.ReactElement {
  return (
    <Alert color="green" withCloseButton onClose={onClear}>
      <Stack gap="sm">
        <Text fw={600}>Signup link created for {email}</Text>
        <Text size="sm" c="dimmed">
          This link is shown once. Copy it before leaving this page.
        </Text>
        <Group gap="sm" align="center" wrap="nowrap">
          <Text size="sm" style={{ wordBreak: "break-all", flex: 1 }}>
            {signupUrl}
          </Text>
          <Button
            size="xs"
            variant="light"
            leftSection={<IconCopy size={14} />}
            onClick={onCopy}
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
  if (dayjs(token.expires_at).valueOf() <= Date.now()) {
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
          {dayjs(token.expires_at).format("YYYY-MM-DD HH:mm")}
        </Text>
      </Table.Td>
      <Table.Td>
        <Text size="sm" c="dimmed">
          {dayjs(token.created_at).format("YYYY-MM-DD HH:mm")}
        </Text>
      </Table.Td>
      <Table.Td>
        <Button
          size="xs"
          variant="subtle"
          color="red"
          leftSection={<IconTrash size={14} />}
          disabled={!revokable}
          onClick={() => onRevokeToken(token.id)}
        >
          Revoke
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

function renderTokenList(
  state: SignupTokenListState,
  onRevokeToken: (tokenId: string) => void,
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
          <Text c="red">{state.message}</Text>
        </Center>
      );
    case "LOADED":
      if (state.tokens.length === 0) {
        return (
          <Center p="xl">
            <Text c="dimmed">No signup links have been created yet.</Text>
          </Center>
        );
      }
      return (
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
            {state.tokens.map((token) => (
              <SignupTokenRow
                key={token.id}
                token={token}
                onRevokeToken={onRevokeToken}
              />
            ))}
          </Table.Tbody>
        </Table>
      );
  }
}

export function SignupTokensPageContent({
  state,
  createState,
  createdToken,
  onCreateToken,
  onCopyCreatedToken,
  onRevokeToken,
  onClearCreatedToken,
}: SignupTokensPageContentProps): React.ReactElement {
  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
      <Stack gap="md" p="md" style={{ flex: 1, minHeight: 0 }}>
        <Stack gap={4}>
          <Title order={4}>Signup links</Title>
          <Text size="sm" c="dimmed">
            Issue manual signup links for users who need account access.
          </Text>
        </Stack>
        <SignupTokenCreateForm
          createState={createState}
          onCreateToken={onCreateToken}
        />
        {createdToken ? (
          <CreatedTokenAlert
            email={createdToken.email}
            signupUrl={createdToken.signupUrl}
            copied={createdToken.copied}
            onCopy={onCopyCreatedToken}
            onClear={onClearCreatedToken}
          />
        ) : null}
        <Paper withBorder style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
          {renderTokenList(state, onRevokeToken)}
        </Paper>
      </Stack>
    </Box>
  );
}
