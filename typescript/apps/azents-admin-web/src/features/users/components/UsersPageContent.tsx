"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { UserDetail } from "./UserDetail";
import { UserList } from "./UserList";
import type { UsersPageContentProps } from "../containers/useUsersPageContainer";

/**
 * Users 페이지 콘텐츠 컴포넌트
 *
 * MasterDetailLayout을 사용한 반응형 2패널 레이아웃
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
