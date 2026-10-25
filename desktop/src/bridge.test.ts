import { beforeEach, expect, test, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { api, bootstrap, finishClose } from "./bridge";
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
const mocked = vi.mocked(invoke);
beforeEach(() => {
  mocked.mockReset();
});
test("API request uses only bounded method/path/body envelope without auth material", async () => {
  mocked.mockResolvedValue({ status: 200, body: { ok: true } });
  expect(await api("/api/projects")).toEqual({ ok: true });
  expect(mocked).toHaveBeenCalledWith("board_request", {
    request: { method: "GET", path: "/api/projects" },
  });
});
test("CAS conflict preserves status for editor conflict path", async () => {
  mocked.mockResolvedValue({
    status: 409,
    body: { error: "다른 창에서 문서가 변경됐습니다." },
  });
  await expect(api("/api/tasks/id/wiki", {})).rejects.toMatchObject({
    httpStatus: 409,
    status: 409,
  });
});
test("native string failures stay visible errors for API and bootstrap", async () => {
  mocked.mockRejectedValue("연결 범위를 확인할 수 없습니다.");
  for (const run of [() => api("/api/projects"), () => bootstrap()]) {
    let caught: unknown;
    try {
      await run();
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(Error);
    expect((caught as Error).message).toBe("연결 범위를 확인할 수 없습니다.");
  }
});
test("close acknowledgment uses exact numeric request ID", async () => {
  mocked.mockResolvedValue(null);
  await finishClose(7, false, "미제출 원문");
  expect(mocked).toHaveBeenCalledWith("finish_close", {
    requestId: 7,
    safe: false,
    reason: "미제출 원문",
  });
});
