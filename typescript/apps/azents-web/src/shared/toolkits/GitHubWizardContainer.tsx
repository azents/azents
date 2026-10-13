"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GitHubWizard } from "./components/GitHubWizard";
import { useGitHubWizardContainer } from "./containers/useGitHubWizardContainer";

export const GitHubWizardContainer = createReactContainer(
  "GitHubWizardContainer",
  useGitHubWizardContainer,
  GitHubWizard,
);
