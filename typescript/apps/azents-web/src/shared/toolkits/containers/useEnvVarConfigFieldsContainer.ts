"use client";
import { useState } from "react";
import type {
  EnvVarConfigFieldsInput,
  EnvVarConfigFieldsProps,
} from "../types";
export function useEnvVarConfigFieldsContainer(
  props: EnvVarConfigFieldsInput,
): EnvVarConfigFieldsProps {
  const [acknowledged, setAcknowledged] = useState(false);
  return { ...props, acknowledged, onAcknowledgedChange: setAcknowledged };
}
