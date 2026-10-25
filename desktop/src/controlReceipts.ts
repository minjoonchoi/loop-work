export type ControlPayload = Readonly<{
  operation_id: string;
  kind: string;
  text: string;
  expected_task_revision: string;
  expected_control_version: number;
  expected_vault_revision: string;
}>;
export type PendingControl = Readonly<{
  projectId: string;
  taskId: string;
  path: string;
  payload: ControlPayload;
}>;
const fields = [
  "operation_id",
  "kind",
  "text",
  "expected_task_revision",
  "expected_control_version",
  "expected_vault_revision",
] as const;
export const controlKey = (projectId: string, taskId: string, kind: string) =>
  JSON.stringify([projectId, taskId, kind]);
export const controlDraftKey = (projectId: string, taskId: string) =>
  "control-text-" + JSON.stringify([projectId, taskId]);
/** A version change is not a receipt. Only the exact original input proves acceptance. */
export function receiptMatches(
  operation: PendingControl,
  receipt: unknown,
): boolean {
  if (!receipt || typeof receipt !== "object") return false;
  const value = receipt as { task_id?: unknown; input?: unknown };
  if (
    value.task_id !== operation.taskId ||
    !value.input ||
    typeof value.input !== "object"
  )
    return false;
  const input = value.input as Record<string, unknown>;
  return (
    Object.keys(input).length === fields.length &&
    fields.every((field) => input[field] === operation.payload[field])
  );
}
