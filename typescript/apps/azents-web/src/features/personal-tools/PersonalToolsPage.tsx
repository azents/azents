"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { PersonalTools } from "./components/PersonalTools";
import { usePersonalToolsContainer } from "./containers/usePersonalToolsContainer";

export const PersonalToolsPage = createReactContainer(
  "PersonalToolsPage",
  usePersonalToolsContainer,
  PersonalTools,
);
