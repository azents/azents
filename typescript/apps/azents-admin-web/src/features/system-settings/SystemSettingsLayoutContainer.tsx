"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SystemSettingsLayout } from "./components/SystemSettingsLayout";
import { useSystemSettingsLayoutContainer } from "./containers/useSystemSettingsLayoutContainer";

export const SystemSettingsLayoutContainer = createReactContainer(
  "SystemSettingsLayout",
  useSystemSettingsLayoutContainer,
  SystemSettingsLayout,
);
