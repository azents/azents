"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GoogleSetup } from "./components/GoogleSetup";
import { useGoogleSetupContainer } from "./containers/useGoogleSetupContainer";

export const GoogleSetupContainer = createReactContainer(
  "GoogleSetupContainer",
  useGoogleSetupContainer,
  GoogleSetup,
);
