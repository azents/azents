"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { PersonalAccess } from "./components/PersonalAccess";
import { usePersonalAccessContainer } from "./containers/usePersonalAccessContainer";

export const PersonalAccessPage = createReactContainer(
  "PersonalAccessPage",
  usePersonalAccessContainer,
  PersonalAccess,
);
