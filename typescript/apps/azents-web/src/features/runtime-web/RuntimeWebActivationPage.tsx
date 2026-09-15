"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeWebActivation } from "./components/RuntimeWebActivation";
import { useRuntimeWebActivationContainer } from "./containers/useRuntimeWebActivationContainer";

export const RuntimeWebActivationPage = createReactContainer(
  "RuntimeWebActivationPage",
  useRuntimeWebActivationContainer,
  RuntimeWebActivation,
);
