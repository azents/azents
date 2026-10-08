"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeWebAuth } from "../components/RuntimeWebAuth";
import { useRuntimeWebAuthContainer } from "./useRuntimeWebAuthContainer";

export const RuntimeWebAuthContainer = createReactContainer(
  "RuntimeWebAuthContainer",
  useRuntimeWebAuthContainer,
  RuntimeWebAuth,
);
