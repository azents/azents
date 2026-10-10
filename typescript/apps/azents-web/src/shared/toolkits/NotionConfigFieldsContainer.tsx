"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { NotionConfigFields } from "./components/NotionConfigFields";
import { useNotionConfigFieldsContainer } from "./containers/useNotionConfigFieldsContainer";
export const NotionConfigFieldsContainer = createReactContainer(
  "NotionConfigFields",
  useNotionConfigFieldsContainer,
  NotionConfigFields,
);
