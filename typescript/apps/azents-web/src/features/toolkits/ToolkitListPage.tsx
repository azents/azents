"use client";

/**
 * Toolkit list page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitList } from "./components/ToolkitList";
import { useToolkitListContainer } from "./containers/useToolkitListContainer";

export const ToolkitListPage = createReactContainer(
  "ToolkitListPage",
  useToolkitListContainer,
  ToolkitList,
);
