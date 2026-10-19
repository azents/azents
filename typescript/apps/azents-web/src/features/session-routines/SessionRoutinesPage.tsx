"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SessionRoutines } from "./components/SessionRoutines";
import { useSessionRoutinesContainer } from "./containers/useSessionRoutinesContainer";

export const SessionRoutinesPage = createReactContainer(
  "SessionRoutinesPage",
  useSessionRoutinesContainer,
  SessionRoutines,
);
