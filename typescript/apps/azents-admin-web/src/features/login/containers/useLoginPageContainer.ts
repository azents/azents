"use client";

import { useLogin } from "@refinedev/core";
import type { LoginState } from "../types";

export interface LoginPageContainerOutput {
  state: LoginState;
  onLogin: () => void;
}

/**
 * 로그인 페이지 컨테이너 훅
 *
 * Refine의 useLogin을 사용하여 GitHub OAuth 로그인을 처리합니다.
 */
export function useLoginPageContainer(): LoginPageContainerOutput {
  const { mutate: login, isPending, error } = useLogin();

  const state: LoginState = error
    ? { type: "ERROR", message: error.message || "로그인에 실패했습니다." }
    : isPending
      ? { type: "LOADING" }
      : { type: "IDLE" };

  const handleLogin = (): void => {
    login({});
  };

  return {
    state,
    onLogin: handleLogin,
  };
}
