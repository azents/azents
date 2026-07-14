export class RequestDeadlineExceededError extends Error {
  public constructor(timeoutMs: number) {
    super(`Request did not settle within ${timeoutMs}ms`);
    this.name = "RequestDeadlineExceededError";
  }
}

export interface RequestDeadlineClock {
  schedule: (
    callback: () => void,
    timeoutMs: number,
  ) => ReturnType<typeof setTimeout>;
  cancel: (timer: ReturnType<typeof setTimeout>) => void;
}

const systemRequestDeadlineClock: RequestDeadlineClock = {
  schedule: (callback, timeoutMs) => setTimeout(callback, timeoutMs),
  cancel: (timer) => clearTimeout(timer),
};

/**
 * Bound caller-visible request latency without cancelling an ambiguous remote
 * commit. Callers can safely retry with the same durable idempotency key.
 */
export function withRequestDeadline<T>(
  request: Promise<T>,
  timeoutMs: number,
  clock: RequestDeadlineClock = systemRequestDeadlineClock,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    let settled = false;
    const timer = clock.schedule(() => {
      if (settled) {
        return;
      }
      settled = true;
      reject(new RequestDeadlineExceededError(timeoutMs));
    }, timeoutMs);

    void request.then(
      (value) => {
        clock.cancel(timer);
        if (settled) {
          return;
        }
        settled = true;
        resolve(value);
      },
      (error: unknown) => {
        clock.cancel(timer);
        if (settled) {
          return;
        }
        settled = true;
        reject(
          error instanceof Error
            ? error
            : new Error("Request failed", { cause: error }),
        );
      },
    );
  });
}
