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
import { IconLogin, IconUserPlus } from "@tabler/icons-react";
import type { LoginPageContainerOutput } from "../containers/useLoginPageContainer";
import type { FormEvent } from "react";

export function LoginPageView({
  state,
  email,
  password,
  setupToken,
  onEmailChange,
  onPasswordChange,
  onSetupTokenChange,
  onSubmit,
}: LoginPageContainerOutput): React.ReactElement {
  const mode = state.type === "LOADING" ? "LOGIN" : state.mode;
  const submitting = state.type === "LOADING" || state.type === "SUBMITTING";
  const bootstrapping = mode === "BOOTSTRAP";

  const handleSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    onSubmit();
  };

  return (
    <Container size="sm" h="100vh">
      <Center h="100%">
        <Paper shadow="md" p="xl" w="100%">
          <form onSubmit={handleSubmit}>
            <Stack gap="md">
              <Stack align="center" gap="xs">
                <Title order={3}>
                  {bootstrapping ? "Set up Azents Admin" : "Azents Admin"}
                </Title>
                <Text c="dimmed" ta="center" size="sm">
                  {bootstrapping
                    ? "Create the first system administrator for this Azents instance."
                    : "Sign in with an Azents system administrator account."}
                </Text>
              </Stack>
              {bootstrapping && (
                <PasswordInput
                  label="Setup token"
                  description="Use the one-time token provided by the Azents server operator."
                  autoComplete="off"
                  value={setupToken}
                  onChange={(event) =>
                    onSetupTokenChange(event.currentTarget.value)
                  }
                  required
                />
              )}
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
                autoComplete={
                  bootstrapping ? "new-password" : "current-password"
                }
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
                leftSection={
                  bootstrapping ? (
                    <IconUserPlus size={20} />
                  ) : (
                    <IconLogin size={20} />
                  )
                }
                loading={submitting}
                disabled={!email || !password || (bootstrapping && !setupToken)}
              >
                {bootstrapping ? "Create system administrator" : "Sign in"}
              </Button>
            </Stack>
          </form>
        </Paper>
      </Center>
    </Container>
  );
}
