import { expect, test } from "vitest";
import {
  controlKey,
  receiptMatches,
  type PendingControl,
} from "./controlReceipts";
const op: PendingControl = {
  projectId: "A",
  taskId: "task",
  path: "/api/tasks/task/control?project_id=A",
  payload: Object.freeze({
    operation_id: "original",
    kind: "pause",
    text: "제출 A",
    expected_task_revision: "task-old",
    expected_control_version: 1,
    expected_vault_revision: "vault-old",
  }),
};
test("only exact nested input and task match confirms original receipt", () => {
  expect(
    receiptMatches(op, { task_id: "task", input: { ...op.payload } }),
  ).toBe(true);
  for (const field of Object.keys(op.payload)) {
    expect(
      receiptMatches(op, {
        task_id: "task",
        input: { ...op.payload, [field]: "changed" },
      }),
    ).toBe(false);
  }
  expect(receiptMatches(op, { task_id: "other", input: op.payload })).toBe(
    false,
  );
  expect(
    receiptMatches(op, {
      task_id: "task",
      operation_id: "original",
      control_version: 2,
    }),
  ).toBe(false);
  expect(
    receiptMatches(op, {
      task_id: "task",
      input: { ...op.payload, extra: true },
    }),
  ).toBe(false);
});
test("same shared task operations remain partitioned by project and kind", () => {
  expect(controlKey("A", "task", "pause")).not.toBe(
    controlKey("B", "task", "pause"),
  );
  expect(controlKey("A", "task", "pause")).not.toBe(
    controlKey("A", "task", "resume"),
  );
});
