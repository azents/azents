"use client";

/**
 * Workspace join request page container
 *
 * Manages logic for non-members to request joining workspace or accept/decline invitation.
 */
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { WorkspaceJoinPageState } from "../types";

export interface WorkspaceJoinContainerProps {
  handle: string;
}

export interface WorkspaceJoinViewProps {
  handle: string;
  state: WorkspaceJoinPageState;
  onSubmitRequest: (message: string | null) => void;
  onAcceptInvitation: () => void;
  onDeclineInvitation: () => void;
}

export function useWorkspaceJoinContainer(
  props: WorkspaceJoinContainerProps,
): WorkspaceJoinViewProps {
  const { handle } = props;

  const utils = trpc.useUtils();

  // Fetch my join request
  const myRequestQuery = trpc.joinRequest.getMyRequest.useQuery(
    { handle },
    {
      retry: false,
    },
  );

  // Fetch my invitation
  const myInvitationQuery = trpc.invitation.getMyInvitation.useQuery(
    { handle },
    {
      retry: false,
    },
  );

  // Create join request
  const createMutation = trpc.joinRequest.create.useMutation({
    onSuccess: () => {
      void utils.joinRequest.getMyRequest.invalidate({ handle });
    },
  });

  // Accept invitation
  const acceptMutation = trpc.invitation.accept.useMutation({
    onSuccess: () => {
      // Redirect to workspace page after acceptance (browser navigation)
      window.location.href = `/w/${handle}`;
    },
  });

  // Decline invitation
  const declineMutation = trpc.invitation.decline.useMutation({
    onSuccess: () => {
      void utils.invitation.getMyInvitation.invalidate({ handle });
    },
  });

  // Determine state
  const state: WorkspaceJoinPageState = useMemo(() => {
    // Loading
    if (myRequestQuery.isLoading || myInvitationQuery.isLoading) {
      return { type: "LOADING" };
    }

    // Prioritize mutation state
    if (createMutation.isPending) {
      return { type: "SUBMITTING" };
    }
    if (createMutation.isSuccess) {
      return { type: "SUBMITTED" };
    }
    if (createMutation.isError) {
      return { type: "ERROR", message: createMutation.error.message };
    }

    // When invitation exists
    if (myInvitationQuery.data && myInvitationQuery.data.status === "pending") {
      return {
        type: "PENDING_INVITATION",
        invitationId: myInvitationQuery.data.id,
      };
    }

    // When join request exists
    if (myRequestQuery.data && myRequestQuery.data.status === "pending") {
      return { type: "PENDING_REQUEST" };
    }

    return { type: "IDLE" };
  }, [
    myRequestQuery.isLoading,
    myRequestQuery.data,
    myInvitationQuery.isLoading,
    myInvitationQuery.data,
    createMutation.isPending,
    createMutation.isSuccess,
    createMutation.isError,
    createMutation.error,
  ]);

  const onSubmitRequest = useCallback(
    (message: string | null): void => {
      createMutation.mutate({ handle, message });
    },
    [handle, createMutation],
  );

  const onAcceptInvitation = useCallback((): void => {
    if (myInvitationQuery.data && myInvitationQuery.data.status === "pending") {
      acceptMutation.mutate({ invitationId: myInvitationQuery.data.id });
    }
  }, [myInvitationQuery.data, acceptMutation]);

  const onDeclineInvitation = useCallback((): void => {
    if (myInvitationQuery.data && myInvitationQuery.data.status === "pending") {
      declineMutation.mutate({ invitationId: myInvitationQuery.data.id });
    }
  }, [myInvitationQuery.data, declineMutation]);

  return {
    handle,
    state,
    onSubmitRequest,
    onAcceptInvitation,
    onDeclineInvitation,
  };
}
