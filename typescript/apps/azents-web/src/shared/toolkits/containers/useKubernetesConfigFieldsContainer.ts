"use client";
import { useState } from "react";
import { getClusters } from "../kubernetes-fields";
import { useProviderConnectionTest } from "./useProviderConnectionTest";
import type {
  KubernetesConfigFieldsProps,
  ToolkitConfigFieldsInput,
} from "../types";
export function useKubernetesConfigFieldsContainer(
  props: ToolkitConfigFieldsInput,
): KubernetesConfigFieldsProps {
  const [replacingCreds, setReplacingCreds] = useState<Set<string>>(new Set());
  const [storedClusterAuthTypes] = useState(
    () =>
      new Map(
        getClusters(props.config)
          .filter((cluster) => cluster.name !== "")
          .map((cluster) => [cluster.name, cluster.auth_type]),
      ),
  );
  return {
    ...props,
    ...useProviderConnectionTest(props, "kubernetes"),
    replacingCreds,
    storedClusterAuthTypes,
    onReplaceCluster: (name) =>
      setReplacingCreds((previous) => new Set(previous).add(name)),
  };
}
