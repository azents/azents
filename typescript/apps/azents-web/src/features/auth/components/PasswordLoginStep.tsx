"use client";

/**
 * Password login component.
 *
 * Email display + password input + login button.
 * Switch to email OTP with "Sign in another way" text button.
 */
import {
  Anchor,
  Button,
  PasswordInput,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { PasswordLoginStepContainerProps } from "../containers/usePasswordLoginStep";

/** Password input form (pure UI) */
function PasswordLoginForm({
  email,
  error,
  isPending,
  onSubmit,
  onUseOtherMethod,
}: {
  email: string;
  error: string | null;
  isPending: boolean;
  onSubmit: (password: string) => void;
  onUseOtherMethod: () => void;
}): React.ReactElement {
  const t = useTranslations("auth");
  const formRef = useRef<HTMLFormElement | null>(null);
  const [password, setPassword] = useState("");

  function syncPasswordState(): void {
    const input = formRef.current?.elements.namedItem("password");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    setPassword(input.value);
  }

  useEffect(() => {
    syncPasswordState();
    const intervalId = window.setInterval(syncPasswordState, 250);

    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    const formData = new FormData(e.currentTarget as HTMLFormElement);
    const password = formData.get("password");
    if (typeof password === "string" && password) {
      onSubmit(password);
    }
  }

  return (
    <form ref={formRef} onSubmit={handleSubmit}>
      <Stack gap="lg">
        <Stack gap="xs" align="center">
          <Title order={2}>{t("passwordStep.headline")}</Title>
          <Text c="dimmed">{email}</Text>
        </Stack>

        <PasswordInput
          name="password"
          autoComplete="current-password"
          placeholder={t("passwordStep.placeholder")}
          onChange={syncPasswordState}
          onInput={syncPasswordState}
          error={error}
          size="lg"
          required
          disabled={isPending}
          autoFocus
        />

        <Button
          type="submit"
          size="lg"
          loading={isPending}
          disabled={isPending || password.length === 0}
        >
          {t("passwordStep.submit")}
        </Button>

        <Anchor
          component="button"
          type="button"
          size="sm"
          c="dimmed"
          onClick={onUseOtherMethod}
          style={{ alignSelf: "center" }}
        >
          {t("passwordStep.useOtherMethod")}
        </Anchor>
      </Stack>
    </form>
  );
}

/** Container -> Component mapping (including FormPageLayout) */
export function PasswordLoginStep({
  state,
  onSubmit,
  onUseOtherMethod,
}: PasswordLoginStepContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <PasswordLoginForm
        email={state.email}
        error={state.type === "IDLE" ? state.error : null}
        isPending={state.type === "SUBMITTING"}
        onSubmit={onSubmit}
        onUseOtherMethod={onUseOtherMethod}
      />
    </FormPageLayout>
  );
}
