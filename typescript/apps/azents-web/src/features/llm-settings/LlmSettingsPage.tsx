"use client";

/**
 * LLM Settings page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LlmSettings } from "./components/LlmSettings";
import { useLlmSettingsContainer } from "./containers/useLlmSettingsContainer";

export const LlmSettingsPage = createReactContainer(
  "LlmSettingsPage",
  useLlmSettingsContainer,
  LlmSettings,
);
