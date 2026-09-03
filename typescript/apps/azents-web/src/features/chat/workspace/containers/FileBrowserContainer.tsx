"use client";

import { useMantineTheme } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { FileBrowser } from "../components/FileBrowser";
import { useWorkspacePanelTranslations } from "./useWorkspacePanelTranslations";
import type { FileBrowserProps } from "../components/FileBrowser";

export function FileBrowserContainer(
  props: FileBrowserProps,
): React.ReactElement {
  const t = useWorkspacePanelTranslations();
  const theme = useMantineTheme();
  const compact = useMediaQuery(`(min-width: ${theme.breakpoints.lg})`);
  return <FileBrowser {...props} compact={compact} t={t} />;
}
