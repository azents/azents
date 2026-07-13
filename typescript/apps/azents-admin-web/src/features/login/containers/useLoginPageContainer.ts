"use client";

import { useLogin } from "@refinedev/core";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { trpc } from "@/trpc/client";
import type { LoginMode, LoginState } from "../types";

export interface LoginPageContainerOutput {
  state: LoginState;
  email: string;
  password: string;
  setupToken: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onSetupTokenChange: (value: string) => void;
  onSubmit: () => void;
}

export function useLoginPageContainer(): LoginPageContainerOutput {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const statusQuery = trpc.bootstrap.status.useQuery();
  const {
    mutate: login,
    isPending: loginPending,
    error: loginError,
  } = useLogin();
  const bootstrap = trpc.bootstrap.firstAdmin.useMutation({
    onSuccess: () => {
      router.replace("/");
      router.refresh();
    },
  });

  const mode: LoginMode = statusQuery.data?.available ? "BOOTSTRAP" : "LOGIN";
  const state: LoginState = statusQuery.isLoading
    ? { type: "LOADING" }
    : statusQuery.isError
      ? { type: "ERROR", mode, message: statusQuery.error.message }
      : loginPending || bootstrap.isPending
        ? { type: "SUBMITTING", mode }
        : loginError || bootstrap.error
          ? {
              type: "ERROR",
              mode,
              message:
                bootstrap.error?.message ??
                loginError?.message ??
                "Sign in failed.",
            }
          : { type: "READY", mode };

  const handleSubmit = (): void => {
    if (mode === "BOOTSTRAP") {
      bootstrap.mutate({ setupToken, email, password });
      return;
    }
    login({ email, password });
  };

  return {
    state,
    email,
    password,
    setupToken,
    onEmailChange: setEmail,
    onPasswordChange: setPassword,
    onSetupTokenChange: setSetupToken,
    onSubmit: handleSubmit,
  };
}
