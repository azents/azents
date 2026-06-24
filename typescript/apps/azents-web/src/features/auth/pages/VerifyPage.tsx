"use client";

/**
 * Verification code validation page
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { VerifyStep } from "../components/VerifyStep";
import { useVerifyStep } from "../containers/useVerifyStep";

export const VerifyPage = createReactContainer(
  "VerifyPage",
  useVerifyStep,
  VerifyStep,
);
