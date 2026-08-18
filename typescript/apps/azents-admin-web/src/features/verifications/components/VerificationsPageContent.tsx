"use client";

import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { VerificationDetail } from "./VerificationDetail";
import { VerificationList } from "./VerificationList";
import type { VerificationsPageContentProps } from "../containers/useVerificationsPageContainer";

/**
 * Verifications page content component
 *
 * Responsive two-panel layout using MasterDetailLayout
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
