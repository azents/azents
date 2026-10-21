import { useTranslations } from "next-intl";

export function useWorkspacePanelTranslations(): ReturnType<
  typeof useTranslations<"chat.workspacePanel">
> {
  return useTranslations("chat.workspacePanel");
}

export type WorkspacePanelTranslator = ReturnType<
  typeof useWorkspacePanelTranslations
>;
