"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { RuntimeProfiles } from "./components/RuntimeProfiles";
import { useRuntimeProfilesContainer } from "./containers/useRuntimeProfilesContainer";

export const RuntimeProfilesPage = createReactContainer(
  "RuntimeProfilesPage",
  useRuntimeProfilesContainer,
  RuntimeProfiles,
);
