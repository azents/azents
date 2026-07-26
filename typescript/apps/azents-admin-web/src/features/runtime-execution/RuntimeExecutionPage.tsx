"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeExecutionPageContent } from "./components/RuntimeExecutionPageContent";
import { useRuntimeExecutionContainer } from "./containers/useRuntimeExecutionContainer";

export const RuntimeExecutionPage = createReactContainer(
  "RuntimeExecutionPage",
  useRuntimeExecutionContainer,
  RuntimeExecutionPageContent,
);
