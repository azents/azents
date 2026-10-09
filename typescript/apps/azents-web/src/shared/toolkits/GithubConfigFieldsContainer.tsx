"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GithubFieldsView } from "./components/GithubFieldsView";
import { useGithubConfigFieldsContainer } from "./containers/useGithubConfigFieldsContainer";
export const GithubConfigFieldsContainer = createReactContainer(
  "GithubConfigFields",
  useGithubConfigFieldsContainer,
  GithubFieldsView,
);
