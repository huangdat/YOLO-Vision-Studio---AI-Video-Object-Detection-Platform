import { useCallback, useEffect, useRef, useState } from "react";
import { connectionError, getSystemInfo, type SystemInfo } from "../api/system";

export type BackendStatus =
  | { state: "checking" }
  | { state: "connected"; info: SystemInfo; checkedAt: Date }
  | { state: "disconnected"; message: string };

export function useBackendStatus() {
  const [status, setStatus] = useState<BackendStatus>({ state: "checking" });
  const request = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setStatus({ state: "checking" });
    try {
      const info = await getSystemInfo(controller.signal);
      if (!controller.signal.aborted)
        setStatus({ state: "connected", info, checkedAt: new Date() });
    } catch (error: unknown) {
      if (!controller.signal.aborted)
        setStatus({ state: "disconnected", message: connectionError(error) });
    }
  }, []);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => {
      void refresh();
    }, 30_000);
    return () => {
      window.clearInterval(interval);
      request.current?.abort();
    };
  }, [refresh]);

  return { status, refresh };
}
