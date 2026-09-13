"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { FontPreviewPageContent } from "./components/FontPreviewPageContent";
import { useFontPreviewPageContainer } from "./containers/useFontPreviewPageContainer";

export const FontPreviewPage = createReactContainer(
  "FontPreviewPage",
  useFontPreviewPageContainer,
  FontPreviewPageContent,
);
