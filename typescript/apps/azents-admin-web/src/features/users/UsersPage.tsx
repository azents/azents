"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { UsersPageContent } from "./components/UsersPageContent";
import { useUsersPageContainer } from "./containers/useUsersPageContainer";

/**
 * Entry point for UsersPage
 *
 * Uses the container pattern to separate state management from UI.
 */
export const UsersPage = createReactContainer(
  "UsersPage",
  useUsersPageContainer,
  UsersPageContent,
);
