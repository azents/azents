// SDK functions and types
export * from "./generated/sdk.gen";
export type * from "./generated/types.gen";

// Client factory and types
export { createClient, createConfig } from "./generated/client";
export type { Client } from "./generated/client";

// Default client instance (for global configuration)
export { client } from "./generated/client.gen";
