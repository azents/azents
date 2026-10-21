"use client";

import { useMediaQuery } from "@mantine/hooks";
import type { MasterDetailLayoutProps } from "../components/MasterDetailLayout";

export interface MasterDetailLayoutOutput extends MasterDetailLayoutProps {
  isDesktop: boolean;
}

export function useMasterDetailLayoutContainer(
  props: MasterDetailLayoutProps,
): MasterDetailLayoutOutput {
  // Keep the existing desktop SSR fallback and Mantine md breakpoint.
  const isDesktop = useMediaQuery("(min-width: 62em)", true);
  return { ...props, isDesktop };
}
