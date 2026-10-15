"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeProvidersPageContent } from "./components/RuntimeProvidersPageContent";
import { useRuntimeProvidersPageContainer } from "./containers/useRuntimeProvidersPageContainer";

export const RuntimeProvidersPage = createReactContainer(
  "RuntimeProvidersPage",
  useRuntimeProvidersPageContainer,
  RuntimeProvidersPageContent,
);
