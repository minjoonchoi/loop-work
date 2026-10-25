export type Project = {
  id: string;
  name: string;
  display_name?: string;
  task_count: number;
  updated_at?: string;
};
export type Row = {
  kind: string;
  id: string;
  record: any;
  display_title?: string;
  board_state?: string;
  state_label?: string;
  review_reasons?: string[];
  state_reason?: string;
  body: string;
  path: string;
  revision: string;
  vault_revision: string;
  modified: boolean;
  fresh: boolean;
  writable: boolean;
  warnings: string[];
  documents?: { path: string; role?: string }[];
  requests?: Row[];
  control?: any;
};
export type BoardData = {
  tasks: Row[];
  requests: Row[];
  warnings: string[];
  vault_status?: { errors?: string[] };
  status?: any;
};
export type Wiki = {
  id: string;
  project_id: string;
  task_id?: string;
  title: string;
  body_markdown: string;
  revision: string;
  path: string;
  editable: boolean;
  warnings: string[];
};
export const states = [
  ["ready", "준비"],
  ["working", "진행 중"],
  ["review", "사용자 확인"],
  ["completed", "완료"],
  ["stopped", "중단"],
] as const;
