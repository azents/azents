"use client";

import { useRouter } from "next/navigation";
/**
 * Workspace list container
 *
 * Fetch authenticated user workspace list and received invitations.
 * Auth guard is handled server-side (page.tsx).
 */
import { useCallback } from "react";
import { trpc } from "@/trpc/client";
import type { InvitationsState, WorkspacesListState } from "../types";

export interface WorkspacesListContainerProps {
  state: WorkspacesListState;
  invitationsState: InvitationsState;
  onSelectWorkspace: (handle: string) => void;
  onCreateWorkspace: () => void;
  onAcceptInvitation: (invitationId: string) => void;
  onDeclineInvitation: (invitationId: string) => void;
  acceptingId: string | null;
  decliningId: string | null;
}

export function useWorkspacesList(): WorkspacesListContainerProps {
  const router = useRouter();
  const utils = trpc.useUtils();

  const workspacesQuery = trpc.workspace.list.useQuery(void 0, {
    retry: false,
  });

  const invitationsQuery = trpc.invitation.listReceived.useQuery(void 0, {
    retry: false,
  });

  const acceptMutation = trpc.invitation.accept.useMutation({
    onSuccess: () => {
      void utils.invitation.listReceived.invalidate();
      void utils.workspace.list.invalidate();
    },
  });

  const declineMutation = trpc.invitation.decline.useMutation({
    onSuccess: () => {
      void utils.invitation.listReceived.invalidate();
    },
  });

  const workspaces = workspacesQuery.data?.items ?? [];

  /** Derive ADT state from query state */
  const state: WorkspacesListState = workspacesQuery.isLoading
    ? { type: "LOADING" }
    : workspacesQuery.isError
      ? { type: "ERROR", error: workspacesQuery.error.message }
      : { type: "READY", workspaces };

  const invitations = invitationsQuery.data?.items ?? [];

  const invitationsState: InvitationsState = invitationsQuery.isLoading
    ? { type: "LOADING" }
    : invitationsQuery.isError
      ? { type: "ERROR" }
      : { type: "READY", invitations };

  const onSelectWorkspace = useCallback(
    (handle: string): void => {
      router.push(`/w/${handle}`);
    },
    [router],
  );

  const onCreateWorkspace = useCallback((): void => {
    router.push("/workspaces/create");
  }, [router]);

  const onAcceptInvitation = useCallback(
    (invitationId: string): void => {
      acceptMutation.mutate({ invitationId });
    },
    [acceptMutation],
  );

  const onDeclineInvitation = useCallback(
    (invitationId: string): void => {
      declineMutation.mutate({ invitationId });
    },
    [declineMutation],
  );

  /** Currently processing invitation ID */
  const acceptingId = acceptMutation.isPending
    ? acceptMutation.variables.invitationId
    : null;
  const decliningId = declineMutation.isPending
    ? declineMutation.variables.invitationId
    : null;

  return {
    state,
    invitationsState,
    onSelectWorkspace,
    onCreateWorkspace,
    onAcceptInvitation,
    onDeclineInvitation,
    acceptingId,
    decliningId,
  };
}
