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
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { usePasswordLoginFormController } from "../containers/usePasswordLoginFormController";
import type { PasswordLoginFormOutput } from "../containers/usePasswordLoginFormController";
import type { PasswordLoginStepContainerProps } from "../containers/usePasswordLoginStep";

const PasswordLoginForm = createReactContainer(
  "PasswordLoginForm",
  usePasswordLoginFormController,
  PasswordLoginFormView,
);

/** Password input form with explicit state and native form callbacks. */
export function PasswordLoginFormView({
  email,
  error,
  isPending,
  onUseOtherMethod,
  formRef,
  password,
  syncPasswordState,
  handleSubmit,
}: PasswordLoginFormOutput): React.ReactElement {
  const t = useTranslations("auth");

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
