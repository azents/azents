"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeWebConfirmation } from "./components/RuntimeWebConfirmation";
import { useRuntimeWebConfirmationContainer } from "./containers/useRuntimeWebConfirmationContainer";

export const RuntimeWebConfirmationPage = createReactContainer(
  "RuntimeWebConfirmationPage",
  useRuntimeWebConfirmationContainer,
  RuntimeWebConfirmation,
);
