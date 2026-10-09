"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { McpConfigFields } from "./components/McpConfigFields";
import { useMcpConfigFieldsContainer } from "./containers/useMcpConfigFieldsContainer";
export const McpConfigFieldsContainer = createReactContainer(
  "McpConfigFields",
  useMcpConfigFieldsContainer,
  McpConfigFields,
);
