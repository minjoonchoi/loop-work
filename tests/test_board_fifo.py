"""Nonregular vault candidates cannot hang the board or its mutation guards."""
from pathlib import Path
import os
import subprocess
import sys
import textwrap
import unittest


class BoardFifoTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO creation unavailable')
    def test_fifo_candidates_are_rejected_without_blocking_healthy_task_actions(self):
        root=Path(__file__).resolve().parents[1]
        code=textwrap.dedent('''
            import os
            import test_board
            from loop_work.board import _read
            from loop_work.storage import LoopError
            fixture=test_board.BoardTests()
            fixture.setUp()
            try:
                # Discovered, unowned 진행 현황.md is scanned by list, detail,
                # and both atomic HumanDesk mutation guards.
                from loop_work.vault_layout import slug
                unsafe=fixture.vault/'프로젝트'/slug('관련 없는 프로젝트','unrelated')/'작업'/slug('FIFO 작업','fifo-task')/'진행 현황.md'
                unsafe.parent.mkdir(parents=True)
                os.mkfifo(unsafe)
                listing=fixture.board.list(include_closed=True)
                assert unsafe.exists(), 'Hidden nonregular documents must be preserved'
                assert len(listing['tasks'])==1, listing
                fixture.test_actual_export_is_display_source_and_normal_approval_resume_remains_guarded()
                # The same low-level protection applies before manifest/history
                # parsing; these are rejected without consuming any FIFO data.
                for name in ('manifest-fifo.json', 'history-fifo.md'):
                    target=fixture.vault/name
                    os.mkfifo(target)
                    try:
                        _read(fixture.vault,name,512)
                    except LoopError:
                        pass
                    else:
                        raise AssertionError('Nonregular candidate was accepted')
                print('FIFO rejected; healthy list/show/respond/execute passed')
            finally:
                fixture.doCleanups()
        ''')
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        env['PYTHONPATH']=str(root/'tests')+os.pathsep+str(root)
        # subprocess.run kills and reaps the isolated child on timeout, so an
        # availability regression cannot leave the suite or a child hung.
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=root,env=env,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('healthy list/show/respond/execute passed',result.stdout)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'FIFO creation unavailable')
    def test_actual_export_manifest_fifo_does_not_block_server_startup_or_database_save(self):
        root=Path(__file__).resolve().parents[1]
        code=textwrap.dedent('''
            import contextlib, http.client, io, json, os, stat
            from unittest.mock import patch
            import test_board
            from loop_work import board_ui
            from loop_work.vault import MAX_EXPORT_JSON
            fixture=test_board.BoardTests(); fixture.setUp()
            try:
                manifest=fixture.kb.home/'vault-owned.json'
                original=manifest.read_bytes(); manifest.unlink(); os.mkfifo(manifest)
                original_inode=manifest.stat().st_ino
                note=fixture.vault/'내 메모'/'개인 기록.md'; note.parent.mkdir(); note.write_text('Keep my note')
                from loop_work import board_service
                result=board_service.start(fixture.kb)
                try:
                    client=http.client.HTTPConnection('127.0.0.1',result['port'],timeout=2)
                    from urllib.parse import urlsplit
                    token=urlsplit(result['url']).fragment
                    client.request('GET','/api/board',headers={'Host':'127.0.0.1:'+str(result['port']),'X-Loop-Capability':token})
                    response=client.getresponse(); assert response.status==200; response.read(); client.close()
                    assert fixture.kb.vault_status()['errors']
                finally:
                    board_service.stop(fixture.kb)
                assert stat.S_ISFIFO(manifest.stat().st_mode) and manifest.stat().st_ino==original_inode
                fixture.kb.put('topic',{'id':'unrelated-save','title':'Retain this save','summary':'Committed despite optional export failure','status':'draft','scope':'task','kind':'note','recorded_at':'2026-10-21'})
                assert fixture.kb.get('topic','unrelated-save')['title']=='Retain this save'
                assert note.read_text()=='Keep my note'
                # Unsafe inventory alternatives are preserved and diagnostic.
                manifest.unlink(); private=fixture.base/'private.json'; private.write_bytes(original)
                manifest.symlink_to(private); assert fixture.kb.sync_vault()['errors']
                assert manifest.is_symlink() and private.read_bytes()==original
                manifest.unlink(); manifest.write_bytes(b' '*(MAX_EXPORT_JSON+1))
                assert fixture.kb.sync_vault()['errors']; assert manifest.stat().st_size==MAX_EXPORT_JSON+1
                manifest.write_bytes(original)
                # Actual exporter counter/status paths must never overwrite FIFO.
                for name in ('vault-export-attempt.json','vault-export-status.json'):
                    path=fixture.kb.home/name; saved=path.read_bytes(); path.unlink(); os.mkfifo(path)
                    inode=path.stat().st_ino; status=fixture.kb.sync_vault()
                    assert status['errors'], status
                    assert stat.S_ISFIFO(path.stat().st_mode) and path.stat().st_ino==inode
                    path.unlink(); path.write_bytes(saved)
                for directory in ('vault-export-status','vault-export'):
                    lock=fixture.kb.home/directory/'.loop/state/lock'
                    saved=lock.read_bytes(); lock.unlink(); os.mkfifo(lock)
                    inode=lock.stat().st_ino; status=fixture.kb.sync_vault()
                    assert status['errors'], status
                    assert stat.S_ISFIFO(lock.stat().st_mode) and lock.stat().st_ino==inode
                    lock.unlink(); lock.write_bytes(saved)
                print('Actual startup HTTP ready; export failure nonfatal; FIFO and notes preserved')
            finally:
                fixture.doCleanups()
        ''')
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        env['PYTHONPATH']=str(root/'tests')+os.pathsep+str(root)
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=root,env=env,
                              capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('Actual startup HTTP ready',result.stdout)
