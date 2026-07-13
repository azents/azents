"use client";

import {
  Button,
  Center,
  Container,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconLogin } from "@tabler/icons-react";
import type { LoginPageContainerOutput } from "../containers/useLoginPageContainer";
import type { FormEvent } from "react";

export function LoginPageView({
  state,
  email,
  password,
  onEmailChange,
  onPasswordChange,
  onLogin,
}: LoginPageContainerOutput): React.ReactElement {
  const isLoading = state.type === "LOADING";

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    onLogin();
  };

  return (
    <Container size="sm" h="100vh">
      <Center h="100%">
        <Paper shadow="md" p="xl" w="100%">
          <form onSubmit={handleSubmit}>
            <Stack gap="md">
              <Stack align="center" gap="xs">
                <Title order={3}>Azents Admin</Title>
                <Text c="dimmed" ta="center" size="sm">
                  Sign in with an Azents system administrator account.
                </Text>
              </Stack>
              <TextInput
                label="Email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => onEmailChange(event.currentTarget.value)}
                required
              />
              <PasswordInput
                label="Password"
                autoComplete="current-password"
                value={password}
                onChange={(event) =>
                  onPasswordChange(event.currentTarget.value)
                }
                required
              />
              {state.type === "ERROR" && (
                <Text c="red" size="sm" role="alert">
                  {state.message}
                </Text>
              )}
              <Button
                type="submit"
                size="lg"
                leftSection={<IconLogin size={20} />}
                loading={isLoading}
                disabled={!email || !password}
              >
                Sign in
              </Button>
            </Stack>
          </form>
        </Paper>
      </Center>
    </Container>
  );
}
