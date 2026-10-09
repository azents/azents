"use client";
import { useDisclosure } from "@mantine/hooks";
import type { RawToolDialogProps } from "../types";

export function useRawToolDialog(): RawToolDialogProps {
  const [rawOpened, { open, close }] = useDisclosure(false);
  return { rawOpened, onOpenRaw: open, onCloseRaw: close };
}
