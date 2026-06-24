"use client";

/**
 * Toolkit create/update page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitForm } from "./components/ToolkitForm";
import { useToolkitFormContainer } from "./containers/useToolkitFormContainer";

export const ToolkitFormPage = createReactContainer(
  "ToolkitFormPage",
  useToolkitFormContainer,
  ToolkitForm,
);
