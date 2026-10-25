import { invoke } from "@tauri-apps/api/core";
export type Scope = {
  project_id?: string | null;
  session_id?: string | null;
  task_id?: string | null;
};
export type Bootstrap = { ready: boolean; scope: Scope; error?: string };
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
  get httpStatus() {
    return this.status;
  }
}
export async function api<T = any>(path: string, body?: unknown): Promise<T> {
  const result = await invoke<{ status: number; body: any }>("board_request", {
    request: {
      method: body === undefined ? "GET" : "POST",
      path,
      ...(body === undefined ? {} : { body }),
    },
  }).catch((error) => {
    throw new Error(error instanceof Error ? error.message : String(error));
  });
  if (result.status < 200 || result.status >= 300)
    throw new ApiError(
      result.body?.error || "요청을 처리하지 못했습니다.",
      result.status,
    );
  return result.body;
}
export const bootstrap = () =>
  invoke<Bootstrap>("bootstrap").catch((error) => {
    throw new Error(error instanceof Error ? error.message : String(error));
  });
export const ready = () => invoke("renderer_ready");
export const finishClose = (
  requestId: number,
  safe: boolean,
  reason?: string,
) => invoke("finish_close", { requestId, safe, ...(reason ? { reason } : {}) });
export const openObsidian = () => invoke("open_obsidian");
export const operationId = () => crypto.randomUUID();
