"use client";

/**
 * Toolkit setup redirect page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitSetup } from "./components/ToolkitSetup";
import { useToolkitSetupContainer } from "./containers/useToolkitSetupContainer";

export const ToolkitSetupPage = createReactContainer(
  "ToolkitSetupPage",
  useToolkitSetupContainer,
  ToolkitSetup,
);
