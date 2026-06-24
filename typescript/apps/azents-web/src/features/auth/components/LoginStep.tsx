"use client";

/**
 * Login step: Email input component
 */
import { Alert, Button, Stack, Text, TextInput, Title } from "@mantine/core";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { LoginStepContainerProps } from "../containers/useLoginStep";

/** Email input form (pure UI) */
function LoginStepForm({
  error,
  isPending,
  signupEmailAvailable,
  signupEmailSent,
  onRequestSignupEmail,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  onRequestSignupEmail: (email: string) => void;
  onSubmit: (email: string) => void;
}): React.ReactElement {
  const t = useTranslations("auth");
  const formRef = useRef<HTMLFormElement | null>(null);
  const [isEmailValid, setIsEmailValid] = useState(false);
  const [currentEmail, setCurrentEmail] = useState("");

  function syncEmailState(): void {
    const input = formRef.current?.elements.namedItem("email");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const nextEmail = input.value;
    const trimmedEmail = nextEmail.trim();
    setCurrentEmail(trimmedEmail);
    setIsEmailValid(trimmedEmail.length > 0 && trimmedEmail.includes("@"));
  }

  useEffect(() => {
    syncEmailState();
    const intervalId = window.setInterval(syncEmailState, 250);

    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    const formData = new FormData(e.currentTarget as HTMLFormElement);
    const email = formData.get("email");
    if (typeof email === "string" && email.trim()) {
      onSubmit(email.trim());
    }
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit}>
      <Stack gap="lg">
        <Stack gap="xs" align="center">
          <Title order={2}>{t("loginStep.headline")}</Title>
          <Text c="dimmed">{t("loginStep.description")}</Text>
        </Stack>

        <TextInput
          type="text"
          inputMode="email"
          name="email"
          autoComplete="email"
          placeholder={t("loginStep.placeholder")}
          onChange={syncEmailState}
          onInput={syncEmailState}
          error={error}
          size="lg"
          disabled={isPending}
        />

        {signupEmailSent ? (
          <Alert color="green">{t("loginStep.signupLinkSent")}</Alert>
        ) : null}

        <Button
          type="submit"
          size="lg"
          loading={isPending}
          disabled={isPending || !isEmailValid}
        >
          {t("loginStep.submit")}
        </Button>
        {signupEmailAvailable ? (
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
  signupEmailAvailable,
  signupEmailSent,
  onRequestSignupEmail,
  onSubmit,
}: LoginStepContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <LoginStepForm
        error={state.type === "IDLE" ? state.error : null}
        isPending={
          state.type === "SENDING" || state.type === "CHECKING_METHODS"
        }
        signupEmailAvailable={signupEmailAvailable}
        signupEmailSent={signupEmailSent}
        onRequestSignupEmail={onRequestSignupEmail}
        onSubmit={onSubmit}
      />
    </FormPageLayout>
  );
}
