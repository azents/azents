"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SignupView } from "../components/SignupView";
import { useSignupContainer } from "../containers/useSignupContainer";

export const SignupPage = createReactContainer(
  "SignupPage",
  useSignupContainer,
  SignupView,
);
