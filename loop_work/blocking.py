"""Evidence-bearing public stop decisions, separate from proven engine failures."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .storage import LoopError, file_hash, now, read_json
from .writing import concise


def remaining_budget(knowledge, task, state, execution):
    budget = knowledge.get('worker-budget', task['id'], required=False) or {'calls': 0}
    seconds = execution.get('max_run_seconds', 14400)
    if state.get('started_at'):
        seconds -= (datetime.now(timezone.utc) - datetime.fromisoformat(state['started_at'])).total_seconds()
    limit = execution.get('max_gate_attempts')
    passed = {'milestone-' + item['id'] for item in state.get('milestones', [])}
    exhausted_gates = [key for key, count in state.get('attempts', {}).items()
                       if limit is not None and count >= limit and key not in passed]
    return {'calls_remaining': max(0, execution.get('max_worker_calls', 40) - budget['calls']),
            'seconds_remaining': max(0, seconds), 'exhausted_gates': exhausted_gates,
            'scope': 'task; per-assignment failure counts do not exhaust the whole task'}


def validate_block(payload, knowledge, task, state, execution, feedback):
    fields = {'version', 'kind', 'reason', 'scope', 'retryable', 'evidence'}
    if not isinstance(payload, dict) or set(payload) != fields or type(payload['version']) is not int or payload['version'] != 1:
        raise LoopError('Public block requires a versioned structured input; reason-only block is no longer supported')
    if payload['kind'] not in ('external', 'user_pause', 'budget_exhausted') or payload['scope'] != 'task':
        raise LoopError('Block kind must be external/user_pause/budget_exhausted at task scope; unit failures require bounded repair/replanning')
    concise(payload['reason'], 'Block reason')
    if type(payload['retryable']) is not bool or not isinstance(payload['evidence'], list):
        raise LoopError('Block needs boolean retryable and evidence list')
    budget = remaining_budget(knowledge, task, state, execution)
    if payload['kind'] == 'user_pause':
        if not feedback.get('paused') or not payload['retryable']:
            raise LoopError('User pause block requires current explicit pause feedback and retryable=true')
    elif payload['kind'] == 'budget_exhausted':
        if budget['calls_remaining'] > 0 and budget['seconds_remaining'] > 0 and not budget['exhausted_gates']:
            raise LoopError('Overall execution budget remains; assignment failures cannot justify whole-task budget exhaustion')
        if payload['retryable']:
            raise LoopError('Exhausted task budget is not retryable')
    elif not payload['evidence']:
        raise LoopError('External blocker requires pinned current evidence')
    for item in payload['evidence']:
        if (not isinstance(item, dict) or set(item) != {'ref', 'sha256'}
                or not isinstance(item['ref'], str) or not isinstance(item['sha256'], str)):
            raise LoopError('Block evidence needs exact ref and mode-aware sha256')
        path = Path(item['ref'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve() != path:
            raise LoopError('Block evidence must be a canonical existing absolute file')
        if file_hash(path) != item['sha256']:
            raise LoopError('Block evidence changed')
    return {**payload, 'budget': budget, 'feedback_revision': feedback['revision'], 'at': now(),
            'validation_scope': 'classification, current pinned evidence and recorded budgets; not an automatic truth judgment'}
