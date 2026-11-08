import { describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { getSystemInfo } from "./system";

describe("system API contract", () => {
  it("requests backend system information and returns the contract", async () => {
    const data = {
      application: "YOLO Vision Studio",
      service: "backend",
      version: "1.0.0",
      status: "UP",
    };
    const get = vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data });
    expect(await getSystemInfo()).toEqual(data);
    expect(get).toHaveBeenCalledWith("/system/info", { signal: undefined });
  });

  it("rejects malformed responses rather than reporting a false connection", async () => {
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({
      data: "<html>proxy fallback</html>",
    });
    await expect(getSystemInfo()).rejects.toThrow("unexpected system response");
  });
});
