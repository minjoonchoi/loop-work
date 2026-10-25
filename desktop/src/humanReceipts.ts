export type PendingHuman = {
  projectId: string; taskId: string; requestId: string;
  action: 'respond' | 'execute'; path: string;
  payload: { expected_revision: number; expected_vault_revision: string; response?: {decision?: string; text: string} };
  original: any; inFlight: boolean;
};
export const humanKey = (project: string, request: string) => JSON.stringify([project, request]);
function canonical(value: any): string {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value && typeof value === 'object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
}
export function humanReceiptMatches(op: PendingHuman, record: any): boolean {
  if (!record || record.id !== op.requestId || record.task_id !== op.taskId) return false;
  const versions = [...(record.history || []), record];
  const prior = versions.find(r=>r.revision===op.payload.expected_revision);
  if (!prior || ['id','task_id','kind','action','response','fingerprint'].some(k=>canonical(prior[k])!==canonical(op.original[k]))) return false;
  if (op.action==='respond') return versions.some(r=>r.revision===op.payload.expected_revision+1 && ['answered','declined'].includes(r.status) && canonical(r.response)===canonical(op.payload.response));
  return versions.some(r=>r.revision===op.payload.expected_revision+2 && ['executed','failed'].includes(r.status) && r.execution?.action==='resume_task' && ['executed','failed'].includes(r.execution?.state) && canonical(r.response)===canonical(op.original.response));
}

export function unchangedHumanRequest(op: PendingHuman, row: any): boolean {
 return !!row && row.fresh===true && row.modified===false && row.writable===true &&
   (row.vault_revision||row.revision)===op.payload.expected_vault_revision && canonical(row.record)===canonical(op.original);
}
