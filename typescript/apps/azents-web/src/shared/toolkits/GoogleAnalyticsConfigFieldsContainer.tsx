"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { GoogleAnalyticsConfigFields } from "./components/GoogleAnalyticsConfigFields";
import { useGoogleAnalyticsConfigFieldsContainer } from "./containers/useGoogleAnalyticsConfigFieldsContainer";
export const GoogleAnalyticsConfigFieldsContainer = createReactContainer(
  "GoogleAnalyticsConfigFields",
  useGoogleAnalyticsConfigFieldsContainer,
  GoogleAnalyticsConfigFields,
);
