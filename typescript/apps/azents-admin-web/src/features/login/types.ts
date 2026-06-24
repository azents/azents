/**
 * Login Feature - ADT (Algebraic Data Types) 정의
 */

// 로그인 상태 ADT
export type LoginState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string };
