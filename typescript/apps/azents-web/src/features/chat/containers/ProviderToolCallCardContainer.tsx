"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ProviderToolCallCard } from "../components/ProviderToolCallCard";
import { useRawToolDialog } from "./useRawToolDialog";
import type {
  ProviderToolCallCardInput,
  ProviderToolCallCardViewProps,
} from "../types";

function useProviderToolCallCard(
  props: ProviderToolCallCardInput,
): ProviderToolCallCardViewProps {
  return { ...props, ...useRawToolDialog() };
}
export const ProviderToolCallCardContainer = createReactContainer(
  "ProviderToolCallCard",
  useProviderToolCallCard,
  ProviderToolCallCard,
);
