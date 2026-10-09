"use client";

/**
 * Toolkit create/update page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitForm } from "../../shared/toolkits/components/ToolkitForm";
import { useToolkitFormContainer } from "../../shared/toolkits/containers/useToolkitFormContainer";

export const ToolkitFormPage = createReactContainer(
  "ToolkitFormPage",
  useToolkitFormContainer,
  ToolkitForm,
);
