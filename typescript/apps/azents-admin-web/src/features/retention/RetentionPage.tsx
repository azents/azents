"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RetentionPageContent } from "./components/RetentionPageContent";
import { useRetentionPageContainer } from "./containers/useRetentionPageContainer";

export const RetentionPage = createReactContainer(
  "RetentionPage",
  useRetentionPageContainer,
  RetentionPageContent,
);
