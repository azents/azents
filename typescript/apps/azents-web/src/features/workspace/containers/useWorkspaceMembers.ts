"use client";

/**
 * Workspace member management container
 *
 * Manages member invite, member list, invitation status, role change, member delete, invite cancel logic.
 */
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  InviteFormState,
  JoinRequestsState,
  MembersState,
  NotificationState,
  WorkspaceInvitationsState,
} from "../types";

export interface WorkspaceMembersContainerProps {
  handle: string;
  currentWorkspaceUserId: string | null;
  currentRole: string | null;
  inviteFormState: InviteFormState;
  membersState: MembersState;
  invitationsState: WorkspaceInvitationsState;
  joinRequestsState: JoinRequestsState;
  notification: NotificationState | null;
  onInvite: (email: string, role: "member" | "manager") => void;
  onClearInviteStatus: () => void;
  onUpdateRole: (
    workspaceUserId: string,
    role: "owner" | "manager" | "member",
  ) => void;
  onRemoveMember: (workspaceUserId: string) => void;
  onCancelInvitation: (invitationId: string) => void;
  onApproveJoinRequest: (joinRequestId: string) => void;
  onRejectJoinRequest: (joinRequestId: string) => void;
  onMuteJoinRequest: (joinRequestId: string) => void;
  onDeleteJoinRequest: (joinRequestId: string) => void;
  onClearNotification: () => void;
}

export function useWorkspaceMembers(props: {
  handle: string;
}): WorkspaceMembersContainerProps {
  const { handle } = props;

  // Invitation form state
  const [inviteFormState, setInviteFormState] = useState<InviteFormState>({
    type: "IDLE",
    error: null,
    success: null,
  });

  // Notification state
  const [notification, setNotification] = useState<NotificationState | null>(
    null,
  );

  const utils = trpc.useUtils();

  // Fetch current user member information
  const meQuery = trpc.workspaceMember.me.useQuery({ handle });
  const currentWorkspaceUserId = meQuery.data?.workspace_user_id ?? null;
  const currentRole = meQuery.data?.role ?? null;

  // Fetch member list
  const membersQuery = trpc.workspaceMember.list.useQuery({ handle });

  // Fetch invitation list
  const invitationsQuery = trpc.invitation.listByWorkspace.useQuery({
    handle,
  });

  // Convert member list state
  const membersState: MembersState = useMemo(() => {
    if (membersQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (membersQuery.isError) {
      return { type: "ERROR" };
    }
    return { type: "READY", members: membersQuery.data?.items ?? [] };
  }, [membersQuery.isLoading, membersQuery.isError, membersQuery.data]);

  // Fetch join request list
  const joinRequestsQuery = trpc.joinRequest.list.useQuery({ handle });

  // Convert invitation list state
  const invitationsState: WorkspaceInvitationsState = useMemo(() => {
    if (invitationsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (invitationsQuery.isError) {
      return { type: "ERROR" };
    }
    return {
      type: "READY",
      invitations: (invitationsQuery.data?.items ?? []).filter(
        (inv) => inv.status === "pending",
      ),
    };
  }, [
    invitationsQuery.isLoading,
    invitationsQuery.isError,
    invitationsQuery.data,
  ]);

  // Convert join request list state
  const joinRequestsState: JoinRequestsState = useMemo(() => {
    if (joinRequestsQuery.isLoading) {
      return { type: "LOADING" };
    }
    if (joinRequestsQuery.isError) {
      return { type: "ERROR" };
    }
    return {
      type: "READY",
      joinRequests: (joinRequestsQuery.data?.items ?? []).filter(
        (jr) => jr.status === "pending",
      ),
    };
  }, [
    joinRequestsQuery.isLoading,
    joinRequestsQuery.isError,
    joinRequestsQuery.data,
  ]);

  // Create invitation
  const inviteMutation = trpc.invitation.create.useMutation({
    onSuccess: () => {
      setInviteFormState({
        type: "IDLE",
        error: null,
        success: "inviteSuccess",
      });
      void utils.invitation.listByWorkspace.invalidate({ handle });
    },
    onError: (error) => {
      const errorKey =
        error.message.includes("member") || error.message.includes("member")
          ? ("inviteAlreadyMember" as const)
          : error.message.includes("invitation") ||
              error.message.includes("invited")
            ? ("inviteAlreadyInvited" as const)
            : ("inviteError" as const);
      setInviteFormState({ type: "IDLE", error: errorKey, success: null });
    },
  });

  // Change role
  const updateRoleMutation = trpc.workspaceMember.updateRole.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "roleUpdateSuccess" });
      void utils.workspaceMember.list.invalidate({ handle });
    },
    onError: (error) => {
      const msg = error.message;
      if (msg.includes("self") || msg.includes("yourself")) {
        setNotification({ type: "error", message: "cannotModifySelf" });
      } else if (msg.includes("Owner")) {
        setNotification({ type: "error", message: "cannotModifyOwner" });
      } else {
        setNotification({ type: "error", message: "roleUpdateError" });
      }
    },
  });

  // Delete member
  const removeMutation = trpc.workspaceMember.remove.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "removeSuccess" });
      void utils.workspaceMember.list.invalidate({ handle });
    },
    onError: (error) => {
      const msg = error.message;
      if (msg.includes("self") || msg.includes("yourself")) {
        setNotification({ type: "error", message: "cannotModifySelf" });
      } else if (msg.includes("Owner")) {
        setNotification({ type: "error", message: "cannotModifyOwner" });
      } else {
        setNotification({ type: "error", message: "removeError" });
      }
    },
  });

  // Cancel invitation
  const cancelInvitationMutation = trpc.invitation.cancel.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "cancelSuccess" });
      void utils.invitation.listByWorkspace.invalidate({ handle });
    },
    onError: () => {
      setNotification({ type: "error", message: "cancelError" });
    },
  });

  // Approve join request
  const approveJoinRequestMutation = trpc.joinRequest.approve.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "approveSuccess" });
      void utils.joinRequest.list.invalidate({ handle });
      void utils.workspaceMember.list.invalidate({ handle });
    },
    onError: () => {
      setNotification({ type: "error", message: "approveError" });
    },
  });

  // Reject join request
  const rejectJoinRequestMutation = trpc.joinRequest.reject.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "rejectSuccess" });
      void utils.joinRequest.list.invalidate({ handle });
    },
    onError: () => {
      setNotification({ type: "error", message: "rejectError" });
    },
  });

  // Mute join request
  const muteJoinRequestMutation = trpc.joinRequest.mute.useMutation({
    onSuccess: () => {
      setNotification({ type: "success", message: "muteSuccess" });
      void utils.joinRequest.list.invalidate({ handle });
    },
    onError: () => {
      setNotification({ type: "error", message: "muteError" });
    },
  });

  // Delete join request
  const deleteJoinRequestMutation = trpc.joinRequest.delete.useMutation({
    onSuccess: () => {
      setNotification({
        type: "success",
        message: "deleteJoinRequestSuccess",
      });
      void utils.joinRequest.list.invalidate({ handle });
    },
    onError: () => {
      setNotification({ type: "error", message: "deleteJoinRequestError" });
    },
  });

  const onInvite = useCallback(
    (email: string, role: "member" | "manager"): void => {
      setInviteFormState({ type: "SENDING" });
      inviteMutation.mutate({ handle, email, role });
    },
    [handle, inviteMutation],
  );

  const onClearInviteStatus = useCallback((): void => {
    setInviteFormState({ type: "IDLE", error: null, success: null });
  }, []);

  const onUpdateRole = useCallback(
    (workspaceUserId: string, role: "owner" | "manager" | "member"): void => {
      updateRoleMutation.mutate({ handle, workspaceUserId, role });
    },
    [handle, updateRoleMutation],
  );

  const onRemoveMember = useCallback(
    (workspaceUserId: string): void => {
      removeMutation.mutate({ handle, workspaceUserId });
    },
    [handle, removeMutation],
  );

  const onCancelInvitation = useCallback(
    (invitationId: string): void => {
      cancelInvitationMutation.mutate({ handle, invitationId });
    },
    [handle, cancelInvitationMutation],
  );

  const onApproveJoinRequest = useCallback(
    (joinRequestId: string): void => {
      approveJoinRequestMutation.mutate({ handle, joinRequestId });
    },
    [handle, approveJoinRequestMutation],
  );

  const onRejectJoinRequest = useCallback(
    (joinRequestId: string): void => {
      rejectJoinRequestMutation.mutate({ handle, joinRequestId });
    },
    [handle, rejectJoinRequestMutation],
  );

  const onMuteJoinRequest = useCallback(
    (joinRequestId: string): void => {
      muteJoinRequestMutation.mutate({ handle, joinRequestId });
    },
    [handle, muteJoinRequestMutation],
  );

  const onDeleteJoinRequest = useCallback(
    (joinRequestId: string): void => {
      deleteJoinRequestMutation.mutate({ handle, joinRequestId });
    },
    [handle, deleteJoinRequestMutation],
  );

  const onClearNotification = useCallback((): void => {
    setNotification(null);
  }, []);

  return {
    handle,
    currentWorkspaceUserId,
    currentRole,
    inviteFormState,
    membersState,
    invitationsState,
    joinRequestsState,
    notification,
    onInvite,
    onClearInviteStatus,
    onUpdateRole,
    onRemoveMember,
    onCancelInvitation,
    onApproveJoinRequest,
    onRejectJoinRequest,
    onMuteJoinRequest,
    onDeleteJoinRequest,
    onClearNotification,
  };
}
