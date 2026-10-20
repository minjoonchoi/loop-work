"""Retain failed work while replacing its completion obligation with accepted work."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contract import identifier
from .storage import LoopError, digest, file_hash, locked, now, read_json, write_json
from .writing import concise


def _get(knowledge, kind, key, db=None, required=True):
    if db is None:
        return knowledge.get(kind, key, required=required)
    row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
    if row:
        return json.loads(row[0])
    if required:
        raise LoopError('Missing retirement dependency: ' + key)


def _key(task_id, assignment_id):
    return 'delegate-' + digest([task_id, assignment_id])[:24]


def _identity(record):
    return digest({k: record.get(k) for k in ('id', 'task_id', 'location_id', 'request', 'status', 'attempts',
        'root', 'candidate_id', 'attempt_file_hash', 'dispatch_digest', 'request_revision', 'request_hash', 'work_unit_id', 'result', 'result_digest',
        'result_file_hash', 'assessment_ref', 'assessment_file_hash', 'feedback_substantive_revision', 'history')})


def _pin(item):
    if (not isinstance(item, dict) or set(item) != {'ref', 'sha256'}
            or not isinstance(item['ref'], str) or not isinstance(item['sha256'], str)):
        raise LoopError('Retirement evidence needs exact ref and mode-aware sha256')
    path = Path(item['ref'])
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.resolve() != path:
        raise LoopError('Retirement evidence must be a canonical current file')
    if file_hash(path) != item['sha256']:
        raise LoopError('Retirement contribution evidence changed: ' + str(path))


def _preserved_failure(knowledge, record):
    from .delegation import Delegation
    runner = Delegation.__new__(Delegation)
    runner.knowledge = knowledge
    runner.validate_retained_evidence(record)


def _receipt_integrity(record):
    for item in [*record.get('history', []), record]:
        path = Path(item['receipt_ref'])
        receipt = read_json(path)
        if file_hash(path) != item['receipt_hash'] or digest(receipt) != item['receipt_digest']:
            raise LoopError('Retirement receipt changed; original barrier remains unresolved')
    return receipt


def _accepted(knowledge, record):
    from .delegation import Delegation, source_path
    if record.get('status') != 'done':
        raise LoopError('Retirement replacement must be accepted done work in the same task')
    runner = Delegation.__new__(Delegation)
    runner.knowledge, runner.task_id, runner.root = knowledge, record['task_id'], Path(record['root'])
    runner.validate_retained_evidence(record)
    value = runner.candidate(record)
    assessment = runner.assessment_receipt(record)
    if assessment.get('verdict') != 'accept' or not all(x.get('satisfied') is True for x in assessment['checks']):
        raise LoopError('Replacement lacks accepted complete criterion evidence')
    # Check just the accepted contribution, not the obsolete whole-checkout digest:
    # a consumer may legitimately edit other files after a producer was accepted.
    originals = read_json(Path(record['directory']) / 'originals.json') if value.get('changes') else []
    modes = {x['path']: x['mode'] for x in originals}
    from .delegation import PreflightKnowledge, contains
    readonly = Delegation(PreflightKnowledge(knowledge.home), record['task_id'], record['root'])
    current = readonly.observation()
    # Write-only accepted outputs need the same current visibility authority.
    # Deletions remain valid absent outputs; inspect no ignored file contents.
    for name in record['request']['write_paths']:
        path = source_path(runner.root, name)
        if path.exists() and name not in current['files']:
            raise LoopError('Accepted replacement write contribution is now ignored/unobserved: ' + name)
    contributions = {}
    for change in value.get('changes', []):
        path = source_path(runner.root, change['path'])
        if change['operation'] == 'patch':
            expected = change['result_hash']
        else:
            expected = 'deleted' if change['operation'] == 'delete' else digest({
            'content': hashlib.sha256(change['content'].encode('utf-8')).hexdigest(),
                'executable': bool(modes[change['path']] & 0o111)})
        if file_hash(path) != expected:
            raise LoopError('Accepted replacement contribution is stale: ' + change['path'])
        contributions[str(path)] = (change['base_hash'], expected)
    # The approval can cite an external receipt while depending on dispatched
    # source. Retain the actual scoped dependency set, including directory membership.
    dispatch = read_json(Path(record['directory']) / 'dispatch.json')
    if digest(dispatch) != record.get('dispatch_digest'):
        raise LoopError('Accepted replacement dispatch evidence changed')
    if 'read_scope' in dispatch:
        # A retained kind pin distinguishes empty-directory/absence changes.
        # Exact accepted outputs have their own final pin and visibility checks.
        inputs = [name for name in record['request']['read_paths']
                  if str(runner.root / name) not in contributions]
        readonly._read_scope({**record['request'], 'read_paths': inputs}, current,
                             {name: kind for name, kind in dispatch['read_scope'].items() if name in inputs})
    scope = record['request']['read_paths'] + record['request']['write_paths']
    # Reuse ordinary read-path validation, checking metadata rather than reading
    # a newly ignored input. Git visibility absence is not physical absence.
    for name in record['request']['read_paths']:
        path = source_path(runner.root, name, directory=True)
        if not name.endswith('/'):
            observed = name in current['files'] or name in current.get('rules', {})
            if path.exists() and not observed:
                raise LoopError('Accepted replacement read dependency is now ignored/unobserved: ' + name)
            # This path's exact accepted final pin was checked before dependency
            # freshness. Its own authorized creation is output, not input drift.
            if str(path) in contributions:
                continue
            originally_absent = name not in dispatch['before']['files'] and name not in dispatch['before'].get('rules', {})
            if originally_absent and path.exists():
                raise LoopError('Accepted replacement absent read dependency now exists: ' + name)
    previous_files = {name: pin for name, pin in dispatch['before']['files'].items() if contains(scope, name)}
    current_files = {name: pin for name, pin in current['files'].items() if contains(scope, name)}
    for name in scope:
        if not name.endswith('/'):
            previous_files.setdefault(name, 'deleted')
            current_files.setdefault(name, 'deleted')
    for name in set(previous_files) | set(current_files):
        if str(runner.root / name) in contributions:
            continue  # its accepted final contribution was checked above
        if previous_files.get(name) != current_files.get(name):
            raise LoopError('Accepted replacement scoped source dependency changed: ' + name)
    # Rule manifests already authorize managed skill links. Do not apply the
    # stricter ordinary-source path policy to these independently observed pins.
    if current.get('rules', {}) != dispatch['before'].get('rules', {}):
        raise LoopError('Accepted replacement source rule dependency changed')
    for check in assessment['checks']:
        for evidence in check.get('evidence', []):
            own_change = contributions.get(evidence['ref'])
            # An accepted edit legitimately replaces the pre-apply base file
            # cited by its original assessment. Its exact accepted output was
            # verified above. All other source/receipt pins remain current.
            if own_change and evidence['sha256'] in own_change:
                continue
            _pin(evidence)
    return value


def _validate(knowledge, task_id, receipt, db=None):
    task = _get(knowledge, 'task', task_id, db)
    from .orchestration import worker_context
    feedback = worker_context(knowledge, task_id, db=db)
    if feedback['blocked'] or feedback['substantive_revision'] != receipt['feedback_substantive_revision']:
        raise LoopError('Retirement feedback authority changed; successful current work is still required')
    if receipt['goal_hash'] != digest(task.get('goal')):
        raise LoopError('Retirement belongs to changed goal criteria')
    old = _get(knowledge, 'delegation', _key(task_id, receipt['assignment_id']), db)
    if old['status'] not in ('rejected', 'blocked', 'failed') or _identity(old) != receipt['original_identity']:
        raise LoopError('Original failed assignment changed after retirement')
    _preserved_failure(knowledge, old)
    original_goal = set(old['request']['planning']['goal_criteria'])
    original_checks = {'assignment:' + x['id'] for x in old['request']['criteria']} | {'goal:' + x for x in original_goal}
    if set(receipt['coverage']) != original_checks:
        raise LoopError('Retirement must cover every original assignment and goal criterion')
    if len(set(receipt['replacements'])) != len(receipt['replacements']) or not receipt['replacements']:
        raise LoopError('Retirement requires distinct accepted replacements')
    contributed = set()
    replacement_goals = {}
    for replacement_id in receipt['replacements']:
        if replacement_id == receipt['assignment_id']:
            raise LoopError('Retirement graph cannot reference itself or form a cycle')
        replacement = _get(knowledge, 'delegation', _key(task_id, replacement_id), db)
        if replacement.get('task_id') != task_id:
            raise LoopError('Retirement replacement belongs to another task')
        if _identity(replacement) != receipt['replacement_identities'][replacement_id]:
            raise LoopError('Accepted replacement identity changed')
        _accepted(knowledge, replacement)
        replacement_goals[replacement_id] = set(replacement['request']['planning']['goal_criteria'])
        contributed.update(replacement_goals[replacement_id])
        existing = _get(knowledge, 'retirement', 'retire-' + digest([task_id, replacement_id])[:24], db, False)
        if existing:
            raise LoopError('Retirement replacements must be terminal accepted work, not another retired edge')
    if not original_goal <= contributed:
        raise LoopError('Accepted replacements do not cover original goal criteria')
    for criterion, ids in receipt['coverage'].items():
        if not isinstance(ids, list) or not ids or not set(ids) <= set(receipt['replacements']):
            raise LoopError('Retirement coverage must identify accepted replacement IDs')
        if criterion.startswith('goal:') and not any(criterion[5:] in replacement_goals[key] for key in ids):
            raise LoopError('Retirement goal coverage does not cite a replacement accepted for that criterion')
    if not receipt['evidence']:
        raise LoopError('Retirement requires current contribution evidence')
    for item in receipt['evidence']:
        _pin(item)
    return old


def is_retired(knowledge, task_id, assignment, db=None):
    key = 'retire-' + digest([task_id, assignment['request']['id']])[:24]
    record = _get(knowledge, 'retirement', key, db, False)
    if record is None:
        return False
    receipt = _receipt_integrity(record)
    _validate(knowledge, task_id, receipt, db)
    return True


def retire(knowledge, task_id, payload):
    fields = {'version', 'assignment_id', 'reason', 'replacements', 'coverage', 'evidence'}
    if not isinstance(payload, dict) or set(payload) != fields or type(payload['version']) is not int or payload['version'] != 1:
        raise LoopError('Retirement requires version/assignment_id/reason/replacements/coverage/evidence')
    if not identifier(payload['assignment_id']) or not isinstance(payload['replacements'], list) or not all(identifier(x) for x in payload['replacements']):
        raise LoopError('Retirement assignment IDs must be valid')
    if not isinstance(payload['coverage'], dict) or not isinstance(payload['evidence'], list):
        raise LoopError('Retirement needs criterion coverage and current pinned evidence')
    concise(payload['reason'], 'Retirement reason')
    key = 'retire-' + digest([task_id, payload['assignment_id']])[:24]
    with locked(knowledge.home / 'task-locks' / task_id):
        with knowledge.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            task = _get(knowledge, 'task', task_id, db)
            if task['phase'] in ('completed', 'aborted'):
                raise LoopError('Cannot retire assignments in terminal tasks')
            previous = _get(knowledge, 'retirement', key, db, False)
            old = _get(knowledge, 'delegation', _key(task_id, payload['assignment_id']), db)
            from .orchestration import worker_context
            feedback = worker_context(knowledge, task_id, db=db)
            receipt = {**payload, 'task_id': task_id, 'feedback_substantive_revision': feedback['substantive_revision'], 'goal_hash': digest(task.get('goal')),
                       'original_identity': _identity(old), 'replacement_identities': {
                           name: _identity(_get(knowledge, 'delegation', _key(task_id, name), db)) for name in payload['replacements']}}
            _validate(knowledge, task_id, receipt, db)
            history = []
            sequence = 1
            if previous:
                stored = _receipt_integrity(previous)
                # Current proof can be refreshed, but every earlier receipt and
                # original failed result stays immutable and hash-checked.
                if stored == receipt:
                    is_retired(knowledge, task_id, old, db)
                    return {'retired': True, 'reused': True, 'retirement': previous}
                history = [*previous.get('history', []), {name: previous[name]
                           for name in ('receipt_ref', 'receipt_hash', 'receipt_digest')}]
                sequence = previous.get('sequence', 1) + 1
            directory = knowledge.home / 'retirements' / task_id
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink() or directory.resolve() != directory:
                raise LoopError('Retirement receipt directory must be a canonical real directory')
            path = directory / (key + '-' + str(sequence) + '.json')
            if path.exists() or path.is_symlink():
                raise LoopError('Retirement artifact already exists; preserve it')
            with path.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
            record = {'id': key, 'task_id': task_id, 'assignment_id': payload['assignment_id'],
                      'receipt_ref': str(path), 'receipt_hash': file_hash(path), 'receipt_digest': digest(receipt),
                      'replacements': payload['replacements'], 'at': now(), 'status': 'retired_obligation',
                      'history': history, 'sequence': sequence}
            knowledge.put('retirement', record, db)
    return {'retired': True, 'reused': False, 'retirement': record,
            'scope': 'Original worker status/history and task budgets are unchanged; completion still requires fresh gates and feedback.'}


def summaries(knowledge, task_id):
    result = []
    for record in knowledge.list('retirement'):
        if record.get('task_id') != task_id:
            continue
        row = {key: record[key] for key in ('assignment_id', 'replacements', 'receipt_ref')}
        try:
            original = knowledge.get('delegation', _key(task_id, record['assignment_id']))
            row['valid'] = is_retired(knowledge, task_id, original)
        except (LoopError, OSError, KeyError, ValueError) as exc:
            row.update(valid=False, error=str(exc))
        result.append(row)
    return result
