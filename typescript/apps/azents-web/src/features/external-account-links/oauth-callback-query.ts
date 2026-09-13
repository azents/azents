export type ExternalAccountOAuthCallbackQuery =
  | { type: "CANCELLED" }
  | { type: "PROVIDER_REJECTED" }
  | { type: "EXCHANGE"; code: string; state: string }
  | { type: "INVALID" };

type QueryValue = string | string[] | null;

const MAX_AUTHORIZATION_CODE_LENGTH = 4096;
const MAX_STATE_LENGTH = 1024;
const MAX_PROVIDER_ERROR_LENGTH = 256;

function boundedValue(maxLength: number, value?: QueryValue): string | null {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= maxLength
    ? value
    : null;
}

export function parseExternalAccountOAuthCallbackQuery(
  query: Record<string, QueryValue>,
): ExternalAccountOAuthCallbackQuery {
  if (Object.hasOwn(query, "error")) {
    const error = boundedValue(MAX_PROVIDER_ERROR_LENGTH, query.error);
    const stateValid =
      !Object.hasOwn(query, "state") ||
      boundedValue(MAX_STATE_LENGTH, query.state) !== null;
    if (error === null || !stateValid) {
      return { type: "INVALID" };
    }
    return error === "access_denied"
      ? { type: "CANCELLED" }
      : { type: "PROVIDER_REJECTED" };
  }

  const code = boundedValue(MAX_AUTHORIZATION_CODE_LENGTH, query.code);
  const state = boundedValue(MAX_STATE_LENGTH, query.state);
  return code === null || state === null
    ? { type: "INVALID" }
    : { type: "EXCHANGE", code, state };
}
