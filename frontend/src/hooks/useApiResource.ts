import { useCallback, useEffect, useRef, useState } from "react";
import { toApiError, type ApiError } from "../api/client";

export type Resource<T> =
  | { status: "loading"; data?: T; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "error"; data?: T; error: ApiError };

/**
 * Loads data for a key. A new key (or reload) aborts the previous request, so responses
 * for outdated parameters can never overwrite newer ones. With keepPreviousData the last
 * successful data stays visible while the next request loads (used for pagination).
 */
export function useApiResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  key: string,
  options: { enabled?: boolean; keepPreviousData?: boolean } = {},
): Resource<T> & { reload: () => void } {
  const { enabled = true, keepPreviousData = false } = options;
  const [state, setState] = useState<Resource<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    setState((previous) => ({
      status: "loading",
      data: keepPreviousData ? previous.data : undefined,
    }));
    loadRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: "success", data });
      },
      (error: unknown) => {
        const apiError = toApiError(error);
        if (!controller.signal.aborted && apiError.kind !== "cancelled") {
          setState({ status: "error", error: apiError });
        }
      },
    );
    return () => controller.abort();
  }, [key, attempt, enabled, keepPreviousData]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, reload };
}
