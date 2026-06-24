"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { VerificationDetail } from "./VerificationDetail";
import { VerificationList } from "./VerificationList";
import type { VerificationsPageContentProps } from "../containers/useVerificationsPageContainer";

/**
 * Verifications 페이지 콘텐츠 컴포넌트
 *
 * MasterDetailLayout을 사용한 반응형 2패널 레이아웃
 */
export function VerificationsPageContent({
  selectedVerificationId,
  onVerificationSelect,
  onDetailClose,
}: VerificationsPageContentProps): React.ReactElement {
  return (
    <MasterDetailLayout
      master={
        <VerificationList
          selectedVerificationId={selectedVerificationId}
          onRowClick={onVerificationSelect}
        />
      }
      detail={<VerificationDetail verificationId={selectedVerificationId} />}
      detailOpen={selectedVerificationId !== null}
      onDetailClose={onDetailClose}
    />
  );
}
