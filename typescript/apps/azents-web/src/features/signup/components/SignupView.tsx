"use client";

import {
  Alert,
  Button,
  Loader,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { SignupContainerProps } from "../containers/useSignupContainer";

function SignupForm({
  emailHint,
  error,
  submitting,
  onSubmit,
}: {
  emailHint: string;
  error: string | null;
  submitting: boolean;
  onSubmit: (email: string, password: string) => void;
}): React.ReactElement {
  const t = useTranslations("auth.signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit(email.trim(), password);
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="lg">
        <Stack gap="xs" align="center">
          <Title order={2}>{t("headline")}</Title>
          <Text c="dimmed">{t("boundDescription", { email: emailHint })}</Text>
        </Stack>
        {error ? <Alert color="red">{error}</Alert> : null}
        <TextInput
          label={t("emailLabel")}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          autoComplete="email"
          type="email"
          size="lg"
          disabled={submitting}
        />
        <PasswordInput
          label={t("passwordLabel")}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          autoComplete="new-password"
          size="lg"
          disabled={submitting}
        />
        <Button
          type="submit"
          size="lg"
          loading={submitting}
          disabled={
            submitting || email.trim().length === 0 || password.length === 0
          }
        >
          {t("submit")}
        </Button>
      </Stack>
    </form>
  );
}

export function SignupView({
  state,
  onSubmit,
}: SignupContainerProps): React.ReactElement {
  const t = useTranslations("auth.signup");

  return (
    <FormPageLayout>
      {state.type === "LOADING" ? (
        <Stack align="center" gap="md">
          <Loader />
          <Text c="dimmed">{t("checking")}</Text>
        </Stack>
      ) : state.type === "ERROR" ? (
        <Stack gap="md" align="center">
          <Title order={2}>{t("errorTitle")}</Title>
          <Text c="red">{state.message}</Text>
        </Stack>
      ) : state.type === "INVALID" ? (
        <Stack gap="md" align="center">
          <Title order={2}>{t("invalidTitle")}</Title>
          <Text c="dimmed">{state.message}</Text>
        </Stack>
      ) : state.type === "SUCCESS" ? (
        <Stack gap="md" align="center">
          <Title order={2}>{t("successTitle")}</Title>
          <Text c="dimmed">{t("successDescription")}</Text>
        </Stack>
      ) : (
        <SignupForm
          emailHint={state.emailHint}
          error={state.error}
          submitting={state.submitting}
          onSubmit={onSubmit}
        />
      )}
    </FormPageLayout>
  );
}
