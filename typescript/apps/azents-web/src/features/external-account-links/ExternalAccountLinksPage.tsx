"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ExternalAccountLinks } from "./components/ExternalAccountLinks";
import { useExternalAccountLinksContainer } from "./containers/useExternalAccountLinksContainer";

export const ExternalAccountLinksPage = createReactContainer(
  "ExternalAccountLinksPage",
  useExternalAccountLinksContainer,
  ExternalAccountLinks,
);
