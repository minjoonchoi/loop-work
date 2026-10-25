from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

from loop_work import board_service as service
from loop_work.board_ui import make_server
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError


class BoardServiceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve()
        self.kb=KnowledgeBase(self.base/'kb',vault_home=self.base/'vault')
        self.addCleanup(self.cleanup_service)

    def cleanup_service(self):
        try: service.stop(self.kb)
        except (LoopError,OSError): pass

    def state(self):
        config=service.configuration(self.kb);key,directory,path=service._paths(self.kb,config)
        return key,directory,path

    def test_real_start_reuses_authenticated_instance_and_stop_is_idempotent(self):
        first=service.start(self.kb)
        self.assertEqual(first['status'],'running');self.assertFalse(first['reused'])
        self.assertEqual(service.status(self.kb)['pid'],first['pid'])
        second=service.start(self.kb)
        self.assertTrue(second['reused']);self.assertEqual(second['instance_nonce'],first['instance_nonce'])
        key,directory,path=self.state()
        self.assertEqual(path.stat().st_mode & 0o777,0o600)
        self.assertEqual((directory/'lock').stat().st_mode & 0o777,0o600)
        self.assertEqual(service.stop(self.kb)['status'],'stopped')
        self.assertTrue(service.stop(self.kb)['reused'])
        third=service.start(self.kb)
        self.assertNotEqual(third['instance_nonce'],first['instance_nonce'])
        self.assertEqual(service.stop(self.kb)['status'],'stopped')

    def test_concurrent_starts_publish_one_instance(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows=list(pool.map(lambda _:service.start(self.kb),range(2)))
        self.assertEqual(rows[0]['pid'],rows[1]['pid']);self.assertEqual(rows[0]['instance_nonce'],rows[1]['instance_nonce'])
        self.assertEqual(sorted(x['reused'] for x in rows),[False,True])

    def test_wrong_nonce_or_pid_never_signals_or_stops_instance(self):
        row=service.start(self.kb);_,_,path=self.state();original=service._read(path)
        for field,value in [('instance_nonce','wrong-'*8),('pid',os.getpid())]:
            with self.subTest(field=field):
                service._write(path,{**original,field:value})
                with patch('os.kill',side_effect=AssertionError('PID termination forbidden')),patch('os.killpg',side_effect=AssertionError('Group termination forbidden')):
                    self.assertEqual(service.status(self.kb)['status'],'unknown')
                    with self.assertRaises(LoopError):service.stop(self.kb)
                service._write(path,original)
                self.assertEqual(service.status(self.kb)['instance_nonce'],row['instance_nonce'])

    def test_unmanaged_server_is_not_stopped_even_with_copied_capability(self):
        server=make_server(self.kb);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(2)))
        config=service.configuration(self.kb);key,directory,path=self.state();service._directory(directory)
        record=dict(version=1,status='running',config_id=key,config=config,instance_nonce='unmanaged-'*5,pid=os.getpid(),port=server.server_port,capability=server.capability_token)
        service._write(path,record)
        with patch('os.kill',side_effect=AssertionError('PID termination forbidden')):
            with self.assertRaises(LoopError):service.stop(self.kb)
        self.assertTrue(thread.is_alive());self.assertEqual(service.status(self.kb)['status'],'unknown')

    def test_port_collision_is_explicit_and_does_not_close_foreign_socket(self):
        sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen();self.addCleanup(sock.close)
        with self.assertRaisesRegex(LoopError,'startup failed'):
            service.start(self.kb,port=sock.getsockname()[1])
        self.assertEqual(service.status(self.kb)['status'],'failed');self.assertGreater(sock.fileno(),0)

    def test_backend_start_retains_internal_authenticated_descriptor(self):
        result=service.start(self.kb)
        self.assertIn('#',result['url']);self.assertEqual(service.status(self.kb)['status'],'running')
        self.assertNotIn('warning',result)

    def test_state_symlink_fifo_and_mode_conflicts_are_bounded_and_preserved(self):
        _,directory,path=self.state();service._directory(directory)
        outside=self.base/'user-note';outside.write_text('keep')
        path.symlink_to(outside)
        with self.assertRaises((LoopError,OSError)):service.start(self.kb)
        self.assertEqual(outside.read_text(),'keep');path.unlink()
        os.mkfifo(path,0o600)
        with self.assertRaises(LoopError):service.status(self.kb)
        self.assertTrue(path.exists());path.unlink()
        path.write_text('{}');path.chmod(0o644)
        with self.assertRaises(LoopError):service.status(self.kb)
        self.assertEqual(path.read_text(),'{}')

    def test_child_exit_before_readiness_is_recorded_without_pid_kill(self):
        class Exited:
            pid=123456
            def poll(self):return 2
            def wait(self):return 2
        with patch.object(service.subprocess,'Popen',return_value=Exited()),patch('os.kill',side_effect=AssertionError('No PID kill')):
            with self.assertRaisesRegex(LoopError,'startup failed'):service.start(self.kb)
        self.assertEqual(service.status(self.kb)['status'],'failed')
