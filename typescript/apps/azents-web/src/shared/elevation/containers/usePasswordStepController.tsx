"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";

export interface PasswordStepViewProps {
  error: {
    error: string | null;
    isPending: boolean;
    onSubmit: (password: string) => void;
  }["error"];
  isPending: {
    error: string | null;
    isPending: boolean;
    onSubmit: (password: string) => void;
  }["isPending"];
  onSubmit: {
    error: string | null;
    isPending: boolean;
    onSubmit: (password: string) => void;
  }["onSubmit"];
  t: ReturnType<typeof useTranslations<"elevation">>;
  password: string;
  setPassword: React.Dispatch<React.SetStateAction<string>>;
  handleSubmit: (e: React.FormEvent) => void;
}
export function usePasswordStepController({
  error,
  isPending,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  onSubmit: (password: string) => void;
}): PasswordStepViewProps {
  const t = useTranslations("elevation");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (password) {
      onSubmit(password);
    }
  }
  return { error, isPending, onSubmit, t, password, setPassword, handleSubmit };
}
