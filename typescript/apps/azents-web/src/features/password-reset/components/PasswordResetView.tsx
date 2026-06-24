"use client";

import {
  Alert,
  Button,
  Center,
  Container,
  Loader,
  Paper,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import Link from "next/link";
import type { PasswordResetContainerProps } from "../containers/usePasswordResetContainer";

export function PasswordResetView({
  state,
  password,
  onPasswordChange,
  onSubmit,
}: PasswordResetContainerProps): React.ReactElement {
  switch (state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader />
        </Center>
      );
    case "INVALID":
      return (
        <PasswordResetShell>
          <Alert color="red" title="Invalid reset link">
            This password reset link is invalid, expired, revoked, or already
            used.
          </Alert>
          <Button component={Link} href="/login" variant="light">
            Go to login
          </Button>
        </PasswordResetShell>
      );
    case "ERROR":
      return (
        <PasswordResetShell>
          <Alert color="red" title="Password reset failed">
            {state.message}
          </Alert>
        </PasswordResetShell>
      );
    case "SUCCESS":
      return (
        <PasswordResetShell>
          <Alert color="green" title="Password updated">
            Your password has been updated. Sign in with your new password.
          </Alert>
          <Button component={Link} href="/login/password">
            Sign in
          </Button>
        </PasswordResetShell>
      );
    case "READY":
    case "SAVING":
      return (
        <PasswordResetShell>
          <Stack gap="md">
            <Text size="sm" c="dimmed">
              Reset password for {state.preview.email ?? "your account"}.
            </Text>
            <PasswordInput
              label="New password"
              value={password}
              onChange={(event) => onPasswordChange(event.currentTarget.value)}
              autoComplete="new-password"
            />
            <Button
              onClick={onSubmit}
              loading={state.type === "SAVING"}
              disabled={password.length === 0}
            >
              Update password
            </Button>
          </Stack>
        </PasswordResetShell>
      );
  }
}

function PasswordResetShell({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <Container size="xs" py="xl">
      <Paper withBorder p="lg" radius="md">
        <Stack gap="lg">
          <div>
            <Title order={2}>Reset password</Title>
            <Text c="dimmed" size="sm">
              Use the reset link issued by your administrator.
            </Text>
          </div>
          {children}
        </Stack>
      </Paper>
    </Container>
  );
}
