"use client";

/**
 * Security page entry point.
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { Security } from "./components/Security";
import { useSecurityContainer } from "./containers/useSecurityContainer";

export const SecurityPage = createReactContainer(
  "SecurityPage",
  useSecurityContainer,
  Security,
);
