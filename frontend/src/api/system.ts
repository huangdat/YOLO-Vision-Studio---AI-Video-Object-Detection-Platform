import axios from "axios";
import { apiClient } from "./client";

export interface SystemInfo {
  application: string;
  service: "backend";
  version: string;
  status: "UP";
}

export async function getSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  const { data } = await apiClient.get<unknown>("/system/info", { signal });
  if (
    typeof data !== "object" ||
    data === null ||
    !("application" in data) ||
    typeof data.application !== "string" ||
    !("version" in data) ||
    typeof data.version !== "string" ||
    !("service" in data) ||
    data.service !== "backend" ||
    !("status" in data) ||
    data.status !== "UP"
  ) {
    throw new Error("The backend returned an unexpected system response.");
  }
  return data as SystemInfo;
}

export function connectionError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    return error.response
      ? `The backend returned HTTP ${error.response.status}. Please try again.`
      : "Unable to reach the backend. Check that the backend is running and try again.";
  }
  return error instanceof Error
    ? error.message
    : "The backend connection could not be verified.";
}
