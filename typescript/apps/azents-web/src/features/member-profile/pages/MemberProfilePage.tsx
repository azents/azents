"use client";

/**
 * Member profile edit page
 *
 * Separates logic/UI with createReactContainer pattern.
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { MemberProfileEdit } from "../components/MemberProfileEdit";
import { useMemberProfileContainer } from "../containers/useMemberProfileContainer";

const MemberProfileContainer = createReactContainer(
  "MemberProfileContainer",
  useMemberProfileContainer,
  MemberProfileEdit,
);

interface MemberProfilePageProps {
  handle: string;
}

export function MemberProfilePage({
  handle,
}: MemberProfilePageProps): React.ReactElement {
  return <MemberProfileContainer handle={handle} />;
}
