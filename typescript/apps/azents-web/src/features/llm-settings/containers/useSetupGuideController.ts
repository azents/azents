"use client";

import { useDisclosure } from "@mantine/hooks";
import type { CredentialType } from "../components/SetupGuide";

export interface SetupGuideInput {
  credType: CredentialType;
  provider: string;
}
export interface SetupGuideOutput extends SetupGuideInput {
  opened: boolean;
  toggle: () => void;
}
export function useSetupGuideController(
  props: SetupGuideInput,
): SetupGuideOutput {
  const [opened, { toggle }] = useDisclosure(false);
  return { ...props, opened, toggle };
}
