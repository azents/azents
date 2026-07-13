"use client";

import { useLogin } from "@refinedev/core";
import { useState } from "react";
import type { LoginState } from "../types";

export interface LoginPageContainerOutput {
  state: LoginState;
  email: string;
  password: string;
  onEmailChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onLogin: () => void;
}

export function useLoginPageContainer(): LoginPageContainerOutput {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { mutate: login, isPending, error } = useLogin();

  const state: LoginState = error
    ? { type: "ERROR", message: error.message || "Login failed." }
    : isPending
      ? { type: "LOADING" }
      : { type: "IDLE" };

  const handleLogin = (): void => {
    login({ email, password });
  };

  return {
    state,
    email,
    password,
    onEmailChange: setEmail,
    onPasswordChange: setPassword,
    onLogin: handleLogin,
  };
}
