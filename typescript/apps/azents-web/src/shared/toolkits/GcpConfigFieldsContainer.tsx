"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GcpConfigFields } from "./components/GcpConfigFields";
import { useGcpConfigFieldsContainer } from "./containers/useGcpConfigFieldsContainer";
export const GcpConfigFieldsContainer = createReactContainer(
  "GcpConfigFields",
  useGcpConfigFieldsContainer,
  GcpConfigFields,
);
