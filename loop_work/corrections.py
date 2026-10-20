"""Typed cumulative corrections retain exact supplied literals, not read authority."""
import copy
import re
from .contract import identifier
from .storage import LoopError

FIELDS = {'id', 'criterion_id', 'origin', 'expected', 'observed', 'source_ref', 'source_hash',
          'validation_owner', 'resolution_status', 'supersedes'}
ORIGINS = {'worker_output', 'assignment_input', 'orchestrator_fixture', 'provider_execution',
           'evidence_staleness', 'unknown'}


def validate_ledger(new, previous, criterion_ids):
    def rows(value):
        if not isinstance(value, list) or len(value) > 100:
            raise LoopError('Correction ledger needs at most one hundred typed items')
        result = {}
        for row in value:
            if (not isinstance(row, dict) or set(row) != FIELDS
                    or not identifier(row.get('id')) or row['id'] in result
                    or not isinstance(row['criterion_id'], str) or row['criterion_id'] not in criterion_ids
                    or not isinstance(row['origin'], str) or row['origin'] not in ORIGINS
                    or row['validation_owner'] not in ('worker', 'orchestrator')
                    or row['resolution_status'] not in ('unresolved', 'resolved')
                    or any(not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > 10000
                           for key in ('expected', 'observed', 'source_ref'))
                    or not isinstance(row['source_hash'], str) or not re.fullmatch('[0-9a-f]{64}', row['source_hash'])
                    or not isinstance(row['supersedes'], list)
                    or any(not identifier(item) for item in row['supersedes'])
                    or len(set(row['supersedes'])) != len(row['supersedes'])):
                raise LoopError('Invalid typed correction ledger item')
            result[row['id']] = row
        return result
    old, current = rows(previous), rows(new)
    if new[:len(previous)] != previous:
        raise LoopError('Prior correction ledger must remain an exact append-only prefix')
    seen = {}
    for key, row in current.items():
        if key in old and row != old[key]:
            raise LoopError('Correction IDs are immutable; append an explicit superseding item')
        for predecessor in row['supersedes']:
            if predecessor not in seen or seen[predecessor]['criterion_id'] != row['criterion_id']:
                raise LoopError('Corrections may supersede only earlier ledger items for the same criterion')
        seen[key] = row
    for key in old:
        if key not in current:
            raise LoopError('Prior corrections must remain in the append-only ledger')
    return copy.deepcopy(new)
