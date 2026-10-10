"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { BraveSearchFieldsView } from "./components/BraveSearchFieldsView";
import { useBraveSearchConfigFieldsContainer } from "./containers/useBraveSearchConfigFieldsContainer";
export const BraveSearchConfigFieldsContainer = createReactContainer(
  "BraveSearchConfigFields",
  useBraveSearchConfigFieldsContainer,
  BraveSearchFieldsView,
);
