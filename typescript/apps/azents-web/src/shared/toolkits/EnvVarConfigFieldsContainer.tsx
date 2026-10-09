"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { EnvVarConfigFields } from "./components/EnvVarConfigFields";
import { useEnvVarConfigFieldsContainer } from "./containers/useEnvVarConfigFieldsContainer";
export const EnvVarConfigFieldsContainer = createReactContainer(
  "EnvVarConfigFields",
  useEnvVarConfigFieldsContainer,
  EnvVarConfigFields,
);
