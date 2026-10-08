"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GitHubUserOAuthCallbackResult } from "./components/GitHubUserOAuthCallbackResult";
import { useGitHubUserOAuthCallbackContainer } from "./containers/useGitHubUserOAuthCallbackContainer";
export const GitHubUserOAuthCallbackPage = createReactContainer(
  "GitHubUserOAuthCallbackPage",
  useGitHubUserOAuthCallbackContainer,
  GitHubUserOAuthCallbackResult,
);
