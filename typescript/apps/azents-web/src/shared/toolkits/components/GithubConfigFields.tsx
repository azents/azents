"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useGithubConfigFieldsContainer } from "../containers/useGithubConfigFieldsContainer";
import { GithubFieldsView } from "./GithubFieldsView";

export const GithubConfigFields = createReactContainer(
  "GithubConfigFields",
  useGithubConfigFieldsContainer,
  GithubFieldsView,
);
