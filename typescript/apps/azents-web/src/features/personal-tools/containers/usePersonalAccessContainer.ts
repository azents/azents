"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { trpc } from "@/trpc/client";
import {
  agentAccessRequests,
  changeConnectionAgent,
  connectionAccessRequest,
  connectionAllows,
  toolkitAllowsAgent,
} from "../access-draft";
import type { ConnectionAccessDraft } from "../access-draft";
import type {
  PersonalAccessProps,
  PersonalAccessState,
  PersonalAccessTarget,
  PersonalWriteState,
} from "../types";
import type { PersonalToolkitResponse } from "@azents/public-client";

export function usePersonalAccessContainer(
  target: PersonalAccessTarget,
): PersonalAccessProps {
  const router = useRouter();
  function returnToOrigin(): void {
    if (target.type === "agent" && target.originSessionId != null) {
      router.push(
        `/w/${encodeURIComponent(target.handle)}/agents/${encodeURIComponent(target.agentId)}/sessions/${encodeURIComponent(target.originSessionId)}`,
      );
    }
  }
  const utils = trpc.useUtils();
  const [search, setSearch] = useState("");
  const [connectionDraft, setConnectionDraft] =
    useState<ConnectionAccessDraft | null>(null);
  const [agentDraft, setAgentDraft] = useState<{
    baseline: PersonalToolkitResponse[];
    changes: Readonly<Record<string, boolean>>;
  } | null>(null);
  const [write, setWrite] = useState<PersonalWriteState>({ type: "IDLE" });
  const me = trpc.user.me.useQuery();
  const connection = trpc.personalToolkit.get.useQuery(
    {
      handle: target.handle,
      toolkitId: target.type === "connection" ? target.toolkitId : "",
    },
    { enabled: target.type === "connection", retry: false },
  );
  const agents = trpc.personalToolkit.eligibleAgents.useQuery(
    { handle: target.handle },
    {
      enabled: target.type === "connection",
      retry: false,
    },
  );
  const agentTools = trpc.personalToolkit.accessForAgent.useQuery(
    {
      handle: target.handle,
      agentId: target.type === "agent" ? target.agentId : "",
    },
    { enabled: target.type === "agent", retry: false },
  );
  const saveConnection = trpc.personalToolkit.saveAccess.useMutation();
  const saveAgent = trpc.personalToolkit.saveAccessForAgent.useMutation();
  const currentConnection =
    connectionDraft ??
    (connection.data == null
      ? null
      : {
          baseline: connection.data,
          mode: connection.data.access_mode,
          changes: {},
        });
  const currentAgent =
    agentDraft ??
    (agentTools.data == null
      ? null
      : {
          baseline: agentTools.data.items,
          changes: {},
        });
  const pending = write.type === "SAVING";
  const dirty = connectionDraft !== null || agentDraft !== null;
  let state: PersonalAccessState;
  if (
    me.isError ||
    (target.type === "connection"
      ? (connection.isError && !connectionDraft) || agents.isError
      : agentTools.isError && !agentDraft)
  ) {
    state = { type: "ERROR" };
  } else if (
    me.data == null ||
    (target.type === "connection"
      ? currentConnection == null || agents.data == null
      : currentAgent == null)
  ) {
    state = { type: "LOADING" };
  } else if (target.type === "connection" && currentConnection && agents.data) {
    const filter = search.trim().toLocaleLowerCase();
    const items = agents.data.items
      .filter((agent) => agent.agent_name.toLocaleLowerCase().includes(filter))
      .map((agent) => ({
        id: agent.agent_id,
        name: agent.agent_name,
        detail: agent.description,
        avatar: agent.avatar,
        allowed: connectionAllows(currentConnection, agent.agent_id),
      }));
    state = {
      type: "READY",
      subject: currentConnection.baseline.name,
      account: me.data.email,
      groups: [{ id: "agents", name: "", items }],
      empty: agents.data.items.length === 0,
      mode: currentConnection.mode,
      firstRestriction:
        currentConnection.baseline.access_mode === "all" &&
        currentConnection.mode === "selected",
    };
  } else if (target.type === "agent" && currentAgent) {
    const filter = search.trim().toLocaleLowerCase();
    const items = currentAgent.baseline
      .filter((toolkit) =>
        `${toolkit.name} ${toolkit.toolkit_type}`
          .toLocaleLowerCase()
          .includes(filter),
      )
      .map((toolkit) => ({
        id: toolkit.id,
        name: toolkit.name,
        detail: toolkit.toolkit_type,
        allowed:
          currentAgent.changes[toolkit.id] ??
          toolkitAllowsAgent(toolkit, target.agentId),
      }));
    state = {
      type: "READY",
      subject: target.agentName,
      account: me.data.email,
      groups: [{ id: "personal", name: "", items }],
      empty: currentAgent.baseline.length === 0,
      mode: null,
      firstRestriction: currentAgent.baseline.some(
        (toolkit) =>
          toolkit.access_mode === "all" &&
          currentAgent.changes[toolkit.id] === false,
      ),
    };
  } else {
    state = { type: "LOADING" };
  }

  async function invalidate(): Promise<void> {
    await Promise.all([
      utils.personalToolkit.list.invalidate({ handle: target.handle }),
      utils.personalToolkit.get.invalidate({ handle: target.handle }),
      utils.personalToolkit.accessForAgent.invalidate({
        handle: target.handle,
      }),
      utils.personalToolkit.eligibleAgents.invalidate({
        handle: target.handle,
      }),
    ]);
  }
  async function save(): Promise<void> {
    if (pending || !dirty) {
      return;
    }
    setWrite({ type: "SAVING" });
    try {
      if (target.type === "connection" && connectionDraft) {
        await saveConnection.mutateAsync({
          handle: target.handle,
          toolkitId: target.toolkitId,
          ...connectionAccessRequest(connectionDraft),
        });
      } else if (target.type === "agent" && agentDraft) {
        await saveAgent.mutateAsync({
          handle: target.handle,
          agentId: target.agentId,
          mutations: agentAccessRequests(
            agentDraft.baseline,
            target.agentId,
            agentDraft.changes,
          ),
        });
      } else {
        return;
      }
    } catch (error) {
      setWrite({
        type: "ERROR",
        conflict:
          typeof error === "object" &&
          error !== null &&
          "data" in error &&
          typeof error.data === "object" &&
          error.data !== null &&
          "code" in error.data &&
          error.data.code === "CONFLICT",
      });
      return;
    }
    // Permission commit is acknowledged. Read failure must not relabel it as a failed save.
    await invalidate().catch(() => {});
    setConnectionDraft(null);
    setAgentDraft(null);
    setWrite({ type: "SAVED" });
    returnToOrigin();
  }

  return {
    state,
    handle: target.handle,
    target: target.type,
    setupHref: target.type === "agent" ? target.setupHref : void 0,
    search,
    dirty,
    write,
    onSearch: setSearch,
    onMode: (mode) => {
      if (!pending && currentConnection) {
        setConnectionDraft({ ...currentConnection, mode, changes: {} });
        setWrite({ type: "IDLE" });
      }
    },
    onToggle: (id, allowed) => {
      if (pending) {
        return;
      }
      if (target.type === "connection" && currentConnection) {
        setConnectionDraft(
          changeConnectionAgent(currentConnection, id, allowed),
        );
      } else if (target.type === "agent" && currentAgent) {
        setAgentDraft({
          ...currentAgent,
          changes: { ...currentAgent.changes, [id]: allowed },
        });
      }
      setWrite({ type: "IDLE" });
    },
    onSave: save,
    onCancel: () => {
      if (pending) {
        return;
      }
      setConnectionDraft(null);
      setAgentDraft(null);
      setWrite({ type: "IDLE" });
      returnToOrigin();
    },
    onReload: () => {
      if (pending) {
        return;
      }
      setConnectionDraft(null);
      setAgentDraft(null);
      setWrite({ type: "IDLE" });
      void invalidate();
      void utils.user.me.invalidate();
    },
  };
}
