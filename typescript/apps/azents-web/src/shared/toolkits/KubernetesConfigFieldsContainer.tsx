"use client";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { KubernetesConfigFields } from "./components/KubernetesConfigFields";
import { useKubernetesConfigFieldsContainer } from "./containers/useKubernetesConfigFieldsContainer";
export const KubernetesConfigFieldsContainer = createReactContainer(
  "KubernetesConfigFields",
  useKubernetesConfigFieldsContainer,
  KubernetesConfigFields,
);
