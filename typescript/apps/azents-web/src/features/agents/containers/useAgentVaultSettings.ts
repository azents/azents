"use client";

import { useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  AgentVaultSettingsProps,
  VaultEditor,
} from "../components/AgentVaultSettings";

export function useAgentVaultSettings(
  handle: string,
  agentId: string,
): AgentVaultSettingsProps {
  const scope = { handle, agentId };
  const settings = trpc.agent.listVaultEntries.useQuery(scope, {
    retry: false,
  });
  const utils = trpc.useUtils();
  const [editor, setEditor] = useState<VaultEditor | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const busy = useRef(false);

  async function submit(name: string, value: string): Promise<void> {
    if (busy.current || editor === null || settings.isError) {
      return;
    }
    busy.current = true;
    setPending(true);
    setError(false);
    try {
      if (editor.type === "delete") {
        await utils.client.agent.deleteVaultEntry.mutate({
          ...scope,
          name: editor.name,
        });
      } else {
        // Imperative calls avoid putting credential variables in the mutation cache.
        await utils.client.agent.writeVaultEntry.mutate({
          ...scope,
          name: editor.type === "replace" ? editor.name : name,
          operation: editor.type,
          value,
        });
      }
      setEditor(null);
      await utils.agent.listVaultEntries.invalidate(scope);
    } catch {
      setError(true);
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return {
    state: settings.isError
      ? { type: "error" }
      : settings.data
        ? { type: "ready", entries: settings.data.entries }
        : { type: "loading" },
    editor,
    pending,
    error,
    onEditor: (next) => {
      if (!busy.current) {
        setError(false);
        setEditor(next);
      }
    },
    onSubmit: submit,
  };
}
