"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import type { PasswordManageState } from "../types";
interface PasswordFormProps {
  hasPassword: boolean;
  state: PasswordManageState;
  onSetPassword: (password: string) => void;
}

export interface PasswordFormViewProps {
  hasPassword: PasswordFormProps["hasPassword"];
  state: PasswordFormProps["state"];
  t: ReturnType<typeof useTranslations<"security">>;
  password: string;
  setPassword: React.Dispatch<React.SetStateAction<string>>;
  confirmPassword: string;
  setConfirmPassword: React.Dispatch<React.SetStateAction<string>>;
  setLocalError: React.Dispatch<React.SetStateAction<string | null>>;
  handleSubmit: (e: React.FormEvent) => void;
  error: string | null;
}
export function usePasswordFormController({
  hasPassword,
  state,
  onSetPassword,
}: PasswordFormProps): PasswordFormViewProps {
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
  return {
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
  };
}
