"use client";

import { useComputedColorScheme } from "@mantine/core";
import type { ChatCodeBlockProps } from "../components/ChatCodeBlock";

export function useChatCodeBlockController(
  props: ChatCodeBlockProps,
): ChatCodeBlockProps & { codeColorScheme: "light" | "dark" } {
  const scheme = useComputedColorScheme("light");
  return { ...props, codeColorScheme: scheme === "dark" ? "dark" : "light" };
}
