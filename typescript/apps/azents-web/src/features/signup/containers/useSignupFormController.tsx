"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";

export interface SignupFormViewProps {
  emailHint: {
    emailHint: string;
    error: string | null;
    submitting: boolean;
    onSubmit: (email: string, password: string) => void;
  }["emailHint"];
  error: {
    emailHint: string;
    error: string | null;
    submitting: boolean;
    onSubmit: (email: string, password: string) => void;
  }["error"];
  submitting: {
    emailHint: string;
    error: string | null;
    submitting: boolean;
    onSubmit: (email: string, password: string) => void;
  }["submitting"];
  onSubmit: {
    emailHint: string;
    error: string | null;
    submitting: boolean;
    onSubmit: (email: string, password: string) => void;
  }["onSubmit"];
  t: ReturnType<typeof useTranslations<"auth.signup">>;
  email: string;
  setEmail: React.Dispatch<React.SetStateAction<string>>;
  password: string;
  setPassword: React.Dispatch<React.SetStateAction<string>>;
  handleSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}
export function useSignupFormController({
  emailHint,
  error,
  submitting,
  onSubmit,
}: {
  emailHint: string;
  error: string | null;
  submitting: boolean;
  onSubmit: (email: string, password: string) => void;
}): SignupFormViewProps {
  const t = useTranslations("auth.signup");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit(email.trim(), password);
  }
  return {
    emailHint,
    error,
    submitting,
    onSubmit,
    t,
    email,
    setEmail,
    password,
    setPassword,
    handleSubmit,
  };
}
