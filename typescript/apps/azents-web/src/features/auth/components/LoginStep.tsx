"use client";

/**
 * Login step: Email input component
 */
import {
  Alert,
  Button,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { LoginStepContainerProps } from "../containers/useLoginStep";

/** Email input form (pure UI) */
function LoginStepForm({
  error,
  isPending,
  emailAvailable,
  signupEmailAvailable,
  signupEmailSent,
  onRequestSignupEmail,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  emailAvailable: boolean;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  onRequestSignupEmail: (email: string) => void;
  onSubmit: (email: string, password: string) => void;
}): React.ReactElement {
  const t = useTranslations("auth");
  const formRef = useRef<HTMLFormElement | null>(null);
  const [isEmailValid, setIsEmailValid] = useState(false);
  const [currentEmail, setCurrentEmail] = useState("");
  const [password, setPassword] = useState("");

  function syncFormState(): void {
    const input = formRef.current?.elements.namedItem("email");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const nextEmail = input.value;
    const trimmedEmail = nextEmail.trim();
    setCurrentEmail(trimmedEmail);
    setIsEmailValid(trimmedEmail.length > 0 && trimmedEmail.includes("@"));
    const passwordInput = formRef.current?.elements.namedItem("password");
    setPassword(
      passwordInput instanceof HTMLInputElement ? passwordInput.value : "",
    );
  }

  useEffect(() => {
    syncFormState();
    const intervalId = window.setInterval(syncFormState, 250);

    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  function handleSubmit(e: React.FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    const formData = new FormData(e.currentTarget);
    const email = formData.get("email");
    const password = formData.get("password");
    if (
      typeof email === "string" &&
      email.trim() &&
      (emailAvailable || (typeof password === "string" && password.length > 0))
    ) {
      onSubmit(email.trim(), typeof password === "string" ? password : "");
    }
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit}>
      <Stack gap="lg">
        <Stack gap="xs" align="center">
          <Title order={2}>
            {t(emailAvailable ? "loginStep.headline" : "passwordStep.submit")}
          </Title>
          {emailAvailable ? (
            <Text c="dimmed">{t("loginStep.description")}</Text>
          ) : null}
        </Stack>

        <TextInput
          type="text"
          inputMode="email"
          name="email"
          autoComplete={emailAvailable ? "email" : "username"}
          label={emailAvailable ? null : t("signup.emailLabel")}
          placeholder={t("loginStep.placeholder")}
          onChange={syncFormState}
          onInput={syncFormState}
          error={emailAvailable ? error : null}
          size="lg"
          disabled={isPending}
        />

        {!emailAvailable ? (
          <PasswordInput
            name="password"
            autoComplete="current-password"
            label={t("signup.passwordLabel")}
            placeholder={t("passwordStep.placeholder")}
            onChange={syncFormState}
            onInput={syncFormState}
            error={error}
            size="lg"
            required
            disabled={isPending}
          />
        ) : null}

        {emailAvailable && signupEmailSent ? (
          <Alert color="green">{t("loginStep.signupLinkSent")}</Alert>
        ) : null}

        <Button
          type="submit"
          size="lg"
          loading={isPending}
          disabled={
            isPending ||
            !isEmailValid ||
            (!emailAvailable && password.length === 0)
          }
        >
          {t(emailAvailable ? "loginStep.submit" : "passwordStep.submit")}
        </Button>
        {emailAvailable && signupEmailAvailable ? (
          <Button
            type="button"
            size="lg"
            variant="light"
            disabled={isPending || !isEmailValid}
            onClick={() => onRequestSignupEmail(currentEmail)}
          >
            {t("loginStep.requestSignupLink")}
          </Button>
        ) : null}
      </Stack>
    </form>
  );
}

/** Container -> Component mapping (including FormPageLayout) */
export function LoginStep({
  state,
  emailAvailable,
  signupEmailAvailable,
  signupEmailSent,
  onRequestSignupEmail,
  onSubmit,
}: LoginStepContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <LoginStepForm
        error={state.type === "IDLE" ? state.error : null}
        isPending={state.type !== "IDLE"}
        emailAvailable={emailAvailable}
        signupEmailAvailable={signupEmailAvailable}
        signupEmailSent={signupEmailSent}
        onRequestSignupEmail={onRequestSignupEmail}
        onSubmit={onSubmit}
      />
    </FormPageLayout>
  );
}
