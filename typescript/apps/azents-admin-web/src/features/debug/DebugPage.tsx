"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { DebugPageContent } from "./components/DebugPageContent";
import { useDebugPageContainer } from "./containers/useDebugPageContainer";

export const DebugPage = createReactContainer(
  "DebugPage",
  useDebugPageContainer,
  DebugPageContent,
);
