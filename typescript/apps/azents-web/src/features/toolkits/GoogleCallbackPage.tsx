"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GoogleCallback } from "./components/GoogleCallback";
import { useGoogleCallbackContainer } from "./containers/useGoogleCallbackContainer";
export const GoogleCallbackPage = createReactContainer(
  "GoogleCallbackPage",
  useGoogleCallbackContainer,
  GoogleCallback,
);
