"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ModelCatalogPageContent } from "./components/ModelCatalogPageContent";
import { useModelCatalogPageContainer } from "./containers/useModelCatalogPageContainer";

export const ModelCatalogPage = createReactContainer(
  "ModelCatalogPage",
  useModelCatalogPageContainer,
  ModelCatalogPageContent,
);
