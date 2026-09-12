"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ExternalAccountLinkConfirmation } from "./components/ExternalAccountLinkConfirmation";
import { useExternalAccountLinkConfirmationContainer } from "./containers/useExternalAccountLinkConfirmationContainer";

export const ExternalAccountLinkConfirmationPage = createReactContainer(
  "ExternalAccountLinkConfirmationPage",
  useExternalAccountLinkConfirmationContainer,
  ExternalAccountLinkConfirmation,
);
