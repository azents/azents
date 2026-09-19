"use client";

import { useMantineTheme } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useCallback, useRef } from "react";
import { FileBrowser } from "../components/FileBrowser";
import { useWorkspacePanelTranslations } from "./useWorkspacePanelTranslations";
import type { FileBrowserProps } from "../components/FileBrowser";

export function FileBrowserContainer(
  props: FileBrowserProps,
): React.ReactElement {
  const { onUploadFiles, ...fileBrowserProps } = props;
  const t = useWorkspacePanelTranslations();
  const theme = useMantineTheme();
  const compact = useMediaQuery(`(min-width: ${theme.breakpoints.lg})`);
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const pendingUploadDirectoryRef = useRef<string | null>(null);
  const handleUploadInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>): void => {
      const files = event.currentTarget.files;
      if (!files || files.length === 0) {
        return;
      }
      const selectedFiles = Array.from(files);
      const destinationDirectory =
        pendingUploadDirectoryRef.current ?? props.cwd;
      pendingUploadDirectoryRef.current = null;
      event.currentTarget.value = "";
      onUploadFiles?.(selectedFiles, destinationDirectory);
    },
    [onUploadFiles, props.cwd],
  );
  const handleOpenUploadPicker = useCallback((directoryPath: string): void => {
    pendingUploadDirectoryRef.current = directoryPath;
    uploadInputRef.current?.click();
  }, []);

  return (
    <>
      <input
        ref={uploadInputRef}
        type="file"
        multiple
        hidden
        data-testid="workspace-upload-input"
        onChange={handleUploadInputChange}
      />
      <FileBrowser
        {...fileBrowserProps}
        compact={compact}
        t={t}
        onOpenUploadPicker={handleOpenUploadPicker}
      />
    </>
  );
}
