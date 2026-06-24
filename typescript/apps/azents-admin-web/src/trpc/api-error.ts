import { TRPCError } from "@trpc/server";
/**
 * API 에러 유틸리티
 *
 * hey-api 에러 인터셉터로 HTTP 상태코드를 보존하고,
 * tRPC 라우터에서 예상된 에러만 선택적으로 변환.
 */
import type { Client } from "@azents/admin-client";

type TRPCErrorCode = ConstructorParameters<typeof TRPCError>[0]["code"];

/** API 서버 HTTP 에러 (상태코드 + 응답 body 포함) */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(extractDetail(body));
    this.name = "ApiError";
  }
}

/** API 에러 body에서 detail 메시지 추출 */
function extractDetail(error: unknown): string {
  // FastAPI validation error (배열 body: [{code, message, ...}])
  if (Array.isArray(error)) {
    return (
      error
        .map((d: { message?: string }) => d.message)
        .filter(Boolean)
        .join(", ") || "입력값이 올바르지 않습니다."
    );
  }
  if (typeof error === "object" && error !== null && "detail" in error) {
    const { detail } = error;
    if (typeof detail === "string") {
      return detail;
    }
    // FastAPI validation error ({detail: [{msg, ...}]})
    if (Array.isArray(detail)) {
      return (
        detail
          .map((d: { msg?: string }) => d.msg)
          .filter(Boolean)
          .join(", ") || "입력값이 올바르지 않습니다."
      );
    }
    // detail이 구조화된 객체이면 JSON 직렬화 (downstream에서 파싱 가능)
    if (typeof detail === "object" && detail !== null) {
      const msg = "message" in detail ? detail.message : null;
      if (typeof msg === "string") {
        return JSON.stringify(detail);
      }
    }
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "알 수 없는 오류가 발생했습니다.";
}

/**
 * API 클라이언트에 에러 인터셉터 등록.
 *
 * HTTP 에러 응답을 ApiError로 래핑하여 상태코드 보존.
 * 네트워크 에러는 원본 그대로 통과.
 */
export function withApiErrorInterceptor(client: Client): Client {
  client.interceptors.error.use((error, response) => {
    if (response instanceof Response) {
      return new ApiError(response.status, error);
    }
    return error;
  });
  return client;
}

/**
 * 예상된 HTTP 에러를 TRPCError로 변환.
 *
 * expected에 포함된 상태코드 → 해당 tRPC 코드로 변환,
 * 그 외 → 원본 에러 그대로 반환 (tRPC가 INTERNAL_SERVER_ERROR로 처리).
 */
export function mapExpectedError(
  error: unknown,
  expected: Partial<Record<number, TRPCErrorCode>>,
): unknown {
  if (error instanceof ApiError) {
    const code = expected[error.status];
    if (code) {
      return new TRPCError({ code, message: error.message });
    }
  }
  return error;
}
