"use client";

/**
 * GitHub PAT settings page UI component.
 *
 * Shows PAT registration or completion screen depending on user state.
 */

import {
  Alert,
  Anchor,
  Button,
  Center,
  Container,
  Loader,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import type { GitHubPATSetupContainerOutput } from "../containers/useGitHubPATSetupContainer";

type GitHubPATSetupProps = GitHubPATSetupContainerOutput;

export function GitHubPATSetup({
  state,
  registerError,
  isRegistering,
  onRegister,
}: GitHubPATSetupProps): React.ReactElement {
  const t = useTranslations("workspace.githubPat");

  switch (state.type) {
    case "LOADING":
      return (
        <Center mih={300}>
          <Loader />
        </Center>
      );

    case "ERROR":
      return (
        <Container size="sm" py="xl">
          <Alert color="red" title={t("error")}>
            {state.message}
          </Alert>
        </Container>
      );

    case "PAT_FORM":
      return (
        <Container size="sm" py="xl">
          <PATRegistrationForm
            onRegister={onRegister}
            registerError={registerError}
            isRegistering={isRegistering}
          />
        </Container>
      );

    case "DONE":
      return (
        <Container size="sm" py="xl">
          <Alert color="green" title={t("setupComplete")}>
            <Text>{t("connectedAs", { username: state.githubUsername })}</Text>
            <Text size="sm" c="dimmed" mt="xs">
              {t("returnToChat")}
            </Text>
          </Alert>
        </Container>
      );
  }
}

/** PAT registration form */
function PATRegistrationForm({
  onRegister,
  registerError,
  isRegistering,
}: {
  onRegister: (token: string) => void;
  registerError: string | null;
  isRegistering: boolean;
}): React.ReactElement {
  const t = useTranslations("workspace.githubPat");
  const [token, setToken] = useState("");

  const handleSubmit = useCallback((): void => {
    if (token.trim()) {
      onRegister(token.trim());
    }
  }, [token, onRegister]);

  return (
    <Stack gap="lg">
      <Title order={2}>{t("registerTitle")}</Title>

      <Stack gap="xs">
        <Text fw={500}>{t("step1Title")}</Text>
        <Anchor
          href="https://github.com/settings/tokens"
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("createOnGitHub")}
        </Anchor>
      </Stack>

      <Stack gap="xs">
        <Text fw={500}>{t("step2Title")}</Text>
        <PasswordInput
          placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
          value={token}
          onChange={(e) => setToken(e.currentTarget.value)}
          disabled={isRegistering}
        />
      </Stack>

      {registerError && (
        <Alert color="red" title={t("invalidToken")}>
          {registerError}
        </Alert>
      )}

      <Button
        onClick={handleSubmit}
        loading={isRegistering}
        disabled={!token.trim()}
      >
        {t("register")}
      </Button>

      <Text size="xs" c="dimmed">
        {t("tokenSecurityNote")}
      </Text>
    </Stack>
  );
}
