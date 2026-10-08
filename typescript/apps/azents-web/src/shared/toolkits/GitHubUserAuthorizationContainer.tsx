"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GitHubUserAuthorization } from "./components/GitHubUserAuthorization";
import { useGitHubUserAuthorizationContainer } from "./containers/useGitHubUserAuthorizationContainer";

export const GitHubUserAuthorizationContainer = createReactContainer(
  "GitHubUserAuthorizationContainer",
  useGitHubUserAuthorizationContainer,
  GitHubUserAuthorization,
);
