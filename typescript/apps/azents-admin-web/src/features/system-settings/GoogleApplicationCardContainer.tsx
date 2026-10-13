"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GoogleApplicationCard } from "./components/GoogleApplicationCard";
import { useGoogleApplicationCardContainer } from "./containers/useGoogleApplicationCardContainer";
export const GoogleApplicationCardContainer = createReactContainer(
  "GoogleApplicationCardContainer",
  useGoogleApplicationCardContainer,
  GoogleApplicationCard,
);
