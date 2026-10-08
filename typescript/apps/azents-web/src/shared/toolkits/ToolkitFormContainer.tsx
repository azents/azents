"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ToolkitForm } from "./components/ToolkitForm";
import { useToolkitFormContainer } from "./containers/useToolkitFormContainer";

export const ToolkitFormContainer = createReactContainer(
  "ToolkitFormContainer",
  useToolkitFormContainer,
  ToolkitForm,
);
