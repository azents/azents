import { useTranslations } from "next-intl";

export function useWorkspacePanelTranslations() {
  return useTranslations("chat.workspacePanel");
}

export type WorkspacePanelTranslator = ReturnType<
  typeof useWorkspacePanelTranslations
>;
