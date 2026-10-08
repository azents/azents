"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GitHubUserAuthorization } from "../../shared/toolkits/components/GitHubUserAuthorization";
import { useGitHubUserAuthorizationContainer } from "../../shared/toolkits/containers/useGitHubUserAuthorizationContainer";

export const GitHubUserAuthorizationPage = createReactContainer(
  "GitHubUserAuthorizationPage",
  useGitHubUserAuthorizationContainer,
  GitHubUserAuthorization,
);
