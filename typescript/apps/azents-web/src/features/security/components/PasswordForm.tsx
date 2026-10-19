"use client";
/**
 * Password setup/change form.
 */
import { Button, PasswordInput, Stack, Text } from "@mantine/core";
import { usePasswordFormController } from "../containers/usePasswordFormController";
import type { PasswordFormViewProps } from "../containers/usePasswordFormController";
import type { PasswordManageState } from "../types";

interface PasswordFormProps {
  hasPassword: boolean;
  state: PasswordManageState;
  onSetPassword: (password: string) => void;
}

export function PasswordForm(props: PasswordFormProps): React.ReactElement {
  return <PasswordFormView {...usePasswordFormController(props)} />;
}

export function PasswordFormView({
  hasPassword,
  state,
  t,
  password,
  setPassword,
  confirmPassword,
  setConfirmPassword,
  setLocalError,
  handleSubmit,
  error,
}: PasswordFormViewProps): React.ReactElement {
  return (
    <Stack gap="md">
      <form onSubmit={handleSubmit}>
        <Stack gap="sm">
          <PasswordInput
            name="new-password"
            autoComplete="new-password"
            label={hasPassword ? t("newPassword") : t("setPassword")}
            placeholder={t("passwordPlaceholder")}
            value={password}
            onChange={(e) => {
              setPassword(e.currentTarget.value);
              setLocalError(null);
            }}
            disabled={state.type === "SAVING"}
          />
          <PasswordInput
            name="confirm-password"
            autoComplete="new-password"
            label={t("confirmPassword")}
            placeholder={t("confirmPasswordPlaceholder")}
            value={confirmPassword}
            onChange={(e) => {
              setConfirmPassword(e.currentTarget.value);
              setLocalError(null);
            }}
            disabled={state.type === "SAVING"}
          />
          {error && (
            <Text size="sm" c="red">
              {error}
            </Text>
          )}
          <Button
            type="submit"
            loading={state.type === "SAVING"}
            disabled={!password || !confirmPassword}
          >
            {hasPassword ? t("changePassword") : t("setPasswordButton")}
          </Button>
        </Stack>
      </form>
    </Stack>
  );
}
