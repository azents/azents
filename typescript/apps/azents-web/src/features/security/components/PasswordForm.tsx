"use client";

/**
 * Password setup/change form.
 */
import { Button, PasswordInput, Stack, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { PasswordManageState } from "../types";

interface PasswordFormProps {
  hasPassword: boolean;
  state: PasswordManageState;
  onSetPassword: (password: string) => void;
}

export function PasswordForm({
  hasPassword,
  state,
  onSetPassword,
}: PasswordFormProps): React.ReactElement {
  const t = useTranslations("security");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (password.length < 8) {
      setLocalError(t("passwordTooShort"));
      return;
    }
    if (password !== confirmPassword) {
      setLocalError(t("passwordMismatch"));
      return;
    }
    setLocalError(null);
    onSetPassword(password);
  }

  const error = localError ?? (state.type === "IDLE" ? state.error : null);

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
