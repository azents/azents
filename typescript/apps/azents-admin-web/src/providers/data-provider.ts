import type { DataProvider } from "@refinedev/core";

/**
 * Refine DataProvider stub
 *
 * All data requests are handled server-side through tRPC.
 * This provider is the minimal stub required to initialize Refine components.
 * It throws an error if an actual data request is made through this provider.
 */

const STUB_ERROR =
  "Direct DataProvider usage is not supported. Request data through tRPC.";

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
