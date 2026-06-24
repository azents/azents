/**
 * Verifications Feature — ADT (Algebraic Data Types) 정의
 */

// --- API 응답 타입 (generated client에서 re-export) ---
export type { EmailVerificationResponse } from "@azents/admin-client";

import type { EmailVerificationResponse } from "@azents/admin-client";

// --- ADT 상태 타입 ---

/** Verification 목록 상태 */
export type VerificationListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      verifications: EmailVerificationResponse[];
    };

/** Verification 상세 상태 */
export type VerificationDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; verificationId: string }
  | { type: "ERROR"; verificationId: string; message: string }
  | {
      type: "LOADED";
      verification: EmailVerificationResponse;
    };
