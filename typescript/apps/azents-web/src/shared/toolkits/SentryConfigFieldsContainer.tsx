"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SentryConfigFields } from "./components/SentryConfigFields";
import { useSentryConfigFieldsContainer } from "./containers/useSentryConfigFieldsContainer";
export const SentryConfigFieldsContainer = createReactContainer(
  "SentryConfigFields",
  useSentryConfigFieldsContainer,
  SentryConfigFields,
);
