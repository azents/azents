"use client";

/**
 * Password login page
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { PasswordLoginStep } from "../components/PasswordLoginStep";
import { usePasswordLoginStep } from "../containers/usePasswordLoginStep";

export const PasswordLoginPage = createReactContainer(
  "PasswordLoginPage",
  usePasswordLoginStep,
  PasswordLoginStep,
);
