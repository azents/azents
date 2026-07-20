"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SystemSettingsPageContent } from "./components/SystemSettingsPageContent";
import { useSystemSettingsPageContainer } from "./containers/useSystemSettingsPageContainer";

export const SystemSettingsPage = createReactContainer(
  "SystemSettingsPage",
  useSystemSettingsPageContainer,
  SystemSettingsPageContent,
);
