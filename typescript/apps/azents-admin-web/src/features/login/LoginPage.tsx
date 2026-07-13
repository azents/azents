"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LoginPageView } from "./components/LoginPageView";
import { useLoginPageContainer } from "./containers/useLoginPageContainer";

export const LoginPage = createReactContainer(
  "LoginPage",
  useLoginPageContainer,
  LoginPageView,
);
