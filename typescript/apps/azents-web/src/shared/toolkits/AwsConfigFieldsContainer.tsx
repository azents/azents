"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AwsConfigFields } from "./components/AwsConfigFields";
import { useAwsConfigFieldsContainer } from "./containers/useAwsConfigFieldsContainer";
export const AwsConfigFieldsContainer = createReactContainer(
  "AwsConfigFields",
  useAwsConfigFieldsContainer,
  AwsConfigFields,
);
