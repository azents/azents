"use client";
import { useState } from "react";
import { projectKubernetesFields } from "../provider-config-views";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  KubernetesConfigFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useKubernetesConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): KubernetesConfigFieldsProps {
  const view = projectKubernetesFields(props.config, props.credentials);
  const [replacingCreds, setReplacingCreds] = useState<Set<string>>(new Set());
  const [storedClusterAuthTypes] = useState(
    () =>
      new Map(
        view.clusters
          .filter((cluster) => cluster.name !== "")
          .map((cluster) => [cluster.name, cluster.auth_type]),
      ),
  );
  return {
    ...props,
    view,
    ...useProviderConnectionTest(props, "kubernetes"),
    replacingCreds,
    storedClusterAuthTypes,
    onReplaceCluster: (name) =>
      setReplacingCreds((previous) => new Set(previous).add(name)),
  };
}
