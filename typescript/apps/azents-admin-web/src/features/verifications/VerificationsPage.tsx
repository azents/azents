"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { VerificationsPageContent } from "./components/VerificationsPageContent";
import { useVerificationsPageContainer } from "./containers/useVerificationsPageContainer";

/**
 * Entry point for VerificationsPage
 *
 * Uses the container pattern to separate state management from UI.
 */
export const VerificationsPage = createReactContainer(
  "VerificationsPage",
  useVerificationsPageContainer,
  VerificationsPageContent,
);
