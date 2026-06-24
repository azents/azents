"use client";

/**
 * GitHub PAT settings page entry point.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";

import { GitHubPATSetup } from "./components/GitHubPATSetup";
import { useGitHubPATSetupContainer } from "./containers/useGitHubPATSetupContainer";

export const GitHubPATSetupPage = createReactContainer(
  "GitHubPATSetupPage",
  useGitHubPATSetupContainer,
  GitHubPATSetup,
);
