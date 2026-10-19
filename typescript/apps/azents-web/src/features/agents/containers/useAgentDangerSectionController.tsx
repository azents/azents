"use client";
import { useDisclosure } from "@mantine/hooks";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
interface AgentDangerSectionProps {
  handle: string;
  agentId: string;
}

export interface AgentDangerSectionViewProps {
  t: ReturnType<typeof useTranslations<"workspace.agents">>;
  tDanger: ReturnType<typeof useTranslations<"workspace.agents.detail.danger">>;
  opened: boolean;
  open: () => void;
  close: () => void;
  deleteMutation: ReturnType<typeof trpc.agent.remove.useMutation>;
  handleDelete: () => void;
}
export function useAgentDangerSectionController({
  handle,
  agentId,
}: AgentDangerSectionProps): AgentDangerSectionViewProps {
  const t = useTranslations("workspace.agents");
  const tDanger = useTranslations("workspace.agents.detail.danger");
  const router = useRouter();
  const utils = trpc.useUtils();
  const [opened, { open, close }] = useDisclosure(false);

  const deleteMutation = trpc.agent.remove.useMutation({
    onSuccess: () => {
      void utils.agent.list.invalidate({ handle });
      router.push(`/w/${handle}/agents`);
    },
  });

  const handleDelete = useCallback(() => {
    deleteMutation.mutate({ handle, agentId });
  }, [deleteMutation, handle, agentId]);
  return { t, tDanger, opened, open, close, deleteMutation, handleDelete };
}
