"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { UserDetail } from "./UserDetail";
import { UserList } from "./UserList";
import type { UsersPageContentProps } from "../containers/useUsersPageContainer";

/**
 * Users page content component
 *
 * Responsive two-panel layout using MasterDetailLayout
 */
export function UsersPageContent({
  selectedUserId,
  onUserSelect,
  onDeleted,
  onDetailClose,
}: UsersPageContentProps): React.ReactElement {
  return (
    <MasterDetailLayout
      master={
        <UserList selectedUserId={selectedUserId} onRowClick={onUserSelect} />
      }
      detail={<UserDetail userId={selectedUserId} onDeleted={onDeleted} />}
      detailOpen={selectedUserId !== null}
      onDetailClose={onDetailClose}
    />
  );
}
