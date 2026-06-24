"use client";

/**
 * Login page
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LoginStep } from "../components/LoginStep";
import { useLoginStep } from "../containers/useLoginStep";

export const LoginPage = createReactContainer(
  "LoginPage",
  useLoginStep,
  LoginStep,
);
