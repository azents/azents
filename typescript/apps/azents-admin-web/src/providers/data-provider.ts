import type { DataProvider } from "@refinedev/core";

/**
 * Refine DataProvider stub
 *
 * 모든 데이터 요청은 tRPC를 통해 서버사이드에서 처리됩니다.
 * 이 provider는 Refine 컴포넌트 초기화에 필요한 최소한의 stub입니다.
 * 실제 데이터 호출이 이 provider를 통해 발생하면 에러를 throw합니다.
 */

const STUB_ERROR =
  "DataProvider를 직접 사용할 수 없습니다. tRPC를 통해 데이터를 요청하세요.";

const throwStub = (): never => {
  throw new Error(STUB_ERROR);
};

export const dataProvider: DataProvider = {
  getList: throwStub,
  getOne: throwStub,
  create: throwStub,
  update: throwStub,
  deleteOne: throwStub,
  getApiUrl: () => "",
};
