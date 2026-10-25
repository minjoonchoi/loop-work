"""Explicit single-task execution binding; sessions retain identity, not routing."""
from __future__ import annotations
import json
from contextlib import nullcontext
from .contract import identifier
from .storage import LoopError, now

TERMINAL = ('completed', 'aborted')


def explicit_skill_task(record):
    """Creation provenance only; binding/session history never supplies it."""
    if not isinstance(record, dict):
        return False
    marker = record.get('provenance')
    return (type(marker) is dict and set(marker) == {'version', 'source'}
            and type(marker.get('version')) is int and marker['version'] == 1
            and marker.get('source') == 'explicit_loop_work')


def activation_status(session, task=None):
    value=session.get('harness',{})
    bound=value.get('scope')=='task' and identifier(value.get('task_id'))
    enabled=bool(bound and value.get('enabled') is True and task and task.get('id')==value['task_id']
                 and task.get('session_id')==session['id'] and task.get('phase') not in TERMINAL)
    return {'session_id':session['id'],'provider':session['provider'],'enabled':enabled,
            'scope':'task','inputs':'related','task_id':value.get('task_id') if bound else None,
            'activated_at':value.get('activated_at'),'updated_at':value.get('updated_at'),
            'released_at':value.get('released_at'),'release_reason':value.get('release_reason')}


class Harness:
    def __init__(self, knowledge): self.knowledge=knowledge

    def status(self, session_id):
        if not identifier(session_id): raise LoopError('Invalid session ID')
        session=self.knowledge.get('session',session_id)
        key=session.get('harness',{}).get('task_id')
        task=self.knowledge.get('task',key,required=False) if identifier(key) else None
        return {**activation_status(session,task),'knowledge_home':str(self.knowledge.home)}

    def on(self, provider, session_id=None, task_id=None):
        if not identifier(task_id):
            raise LoopError('Explicit task_id is required; create the task before binding it')
        with self.knowledge.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT body FROM records WHERE kind='task' AND id=?",(task_id,)).fetchone()
            if row is None: raise LoopError('Unknown task: '+task_id)
            task=json.loads(row[0]); selected=task['session_id']
            if session_id is not None and session_id!=selected: raise LoopError('Task must belong to the selected session')
            row=db.execute("SELECT body FROM records WHERE kind='session' AND id=?",(selected,)).fetchone()
            if row is None: raise LoopError('Task session is missing')
            session=json.loads(row[0])
            if session['provider']!=provider or task['provider']!=provider: raise LoopError('Task and session must belong to the requested provider')
            if task['phase'] in TERMINAL: raise LoopError('Terminal tasks cannot be rebound; create a new task')
            current=session.get('harness',{})
            if current.get('scope')=='task' and current.get('enabled') is True and current.get('task_id')!=task_id:
                other=db.execute("SELECT body FROM records WHERE kind='task' AND id=?",(current.get('task_id'),)).fetchone()
                if other and json.loads(other[0]).get('phase') not in TERMINAL:
                    raise LoopError('Another unfinished task is bound to this session')
            if not (current.get('scope')=='task' and current.get('task_id')==task_id and current.get('enabled') is True):
                stamp=now()
                session['harness']={'enabled':True,'scope':'task','task_id':task_id,'inputs':'related',
                                    'activated_at':stamp,'updated_at':stamp,'generation':current.get('generation',0)+1}
                self.knowledge.put('session',session,db)
        return self.status(selected)

    def off(self, session_id):
        if not identifier(session_id): raise LoopError('Invalid session ID')
        with self.knowledge.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT body FROM records WHERE kind='session' AND id=?",(session_id,)).fetchone()
            if row is None: raise LoopError('Unknown session: '+session_id)
            session=json.loads(row[0]); value=session.get('harness',{})
            if value.get('enabled') is True:
                stamp=now()
                session['harness']={**value,'enabled':False,'updated_at':stamp,'released_at':stamp,'release_reason':'manual_interrupt'}
                self.knowledge.put('session',session,db)
        return self.status(session_id)


def cancellation_probe(knowledge,task_id):
    """Read task-local controls only; never cancel unrelated low-level work."""
    task=knowledge.get('task',task_id)
    session=knowledge.get('session',task['session_id'])
    binding=session.get('harness',{})
    was_bound=binding.get('scope')=='task' and binding.get('task_id')==task_id and binding.get('enabled') is True
    controls=knowledge.list('feedback')
    initial_seq=max((row.get('seq',0) for row in controls if row.get('task_id')==task_id and row.get('session_id')==task['session_id']),default=0)
    def cancelled(db=None):
        supplied=db is not None
        with nullcontext(db) if supplied else knowledge.connection() as db:
            if not supplied:
                db.execute("BEGIN")
            row=db.execute("SELECT body FROM records WHERE kind='task' AND id=?",(task_id,)).fetchone()
            if row is None or json.loads(row[0]).get('phase') in TERMINAL:
                return 'Task stopped or completed'
            controls=[json.loads(row[0]) for row in db.execute("SELECT body FROM records WHERE kind='feedback'")]
            controls=[row for row in controls if row.get('task_id')==task_id and row.get('session_id')==task['session_id'] and row.get('kind') in ('pause','resume')]
            if any(row['kind']=='pause' and row['seq']>initial_seq for row in controls):
                return 'User interrupted this call; a later resume cannot revive the old process'
            if controls and max(controls,key=lambda row:row['seq'])['kind']=='pause':
                return 'User paused this task; explicit resume is required'
            if binding.get('scope')=='task' and binding.get('task_id')==task_id and binding.get('enabled') is not True:
                return 'Task binding is interrupted; explicitly bind this task before execution'
            if was_bound:
                row=db.execute("SELECT body FROM records WHERE kind='session' AND id=?",(task['session_id'],)).fetchone()
                current=json.loads(row[0]).get('harness',{}) if row else {}
                if current.get('scope')!='task' or current.get('task_id')!=task_id or current.get('enabled') is not True or current.get('generation')!=binding.get('generation'):
                    return 'Task binding was interrupted; explicit task resume is required'
        return None
    return cancelled
