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
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { LoginStepContainerProps, LoginStepFormState } from "../types";

/** Email input form (pure UI) */
function LoginStepForm({
  error,
  isPending,
  emailAvailable,
  signupEmailAvailable,
  signupEmailSent,
  form,
}: {
  error: string | null;
  isPending: boolean;
  emailAvailable: boolean;
  signupEmailAvailable: boolean;
  signupEmailSent: boolean;
  form: LoginStepFormState;
}): React.ReactElement {
  const t = useTranslations("auth");

  return (
    <form ref={form.formRef} onSubmit={form.onSubmit}>
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
          onChange={form.onInput}
          onInput={form.onInput}
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
            onChange={form.onInput}
            onInput={form.onInput}
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
            !form.emailValid ||
            (!emailAvailable && !form.passwordPresent)
          }
        >
          {t(emailAvailable ? "loginStep.submit" : "passwordStep.submit")}
        </Button>
        {emailAvailable && signupEmailAvailable ? (
          <Button
            type="button"
            size="lg"
            variant="light"
            disabled={isPending || !form.emailValid}
            onClick={form.onRequestSignupEmail}
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
  form,
}: LoginStepContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      <LoginStepForm
        error={state.type === "IDLE" ? state.error : null}
        isPending={state.type !== "IDLE"}
        emailAvailable={emailAvailable}
        signupEmailAvailable={signupEmailAvailable}
        signupEmailSent={signupEmailSent}
        form={form}
      />
    </FormPageLayout>
  );
}
