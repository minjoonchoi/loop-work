import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from loop_work.cli import main,parser

class DesktopCliTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.base=Path(t.name).resolve();self.common=['--knowledge-home',str(self.base/'kb')]
    def run_cli(self,args):
        with contextlib.redirect_stdout(io.StringIO()):return main(self.common+args,entrypoint=str(self.base/'installed/loop.py'))
    def test_bare_board_and_open_route_native_with_exact_scopes(self):
        self.assertEqual(parser().parse_args(['board']).board_command,'open')
        with patch('loop_work.desktop.open_app',return_value={'status':'opening'}) as launch:
            self.assertEqual(self.run_cli(['board']),0)
            self.assertEqual(self.run_cli(['board','open','--vault',str(self.base/'vault'),'--project','p','--session','s','--task','t']),0)
        call=launch.call_args;self.assertEqual(call.args[2:],('s','t','p'));self.assertEqual(call.kwargs['entrypoint'],str(self.base/'installed/loop.py'))
    def test_retired_commands_rejected_before_any_runtime_or_knowledge_side_effect(self):
        retired=[['board','serve'],['human','serve']]
        retired += [['board',cmd,flag] for cmd in ('open','_desktop','start') for flag in ('--web','--no-open')]
        for argv in retired:
            with self.subTest(argv=argv),patch('loop_work.cli.KnowledgeBase',side_effect=AssertionError('must not construct knowledge')),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:self.run_cli(argv)
                self.assertEqual(error.exception.code,2)
                self.assertFalse((self.base/'kb').exists())
    def test_lifecycle_is_backend_only_and_public_output_hides_capability(self):
        for command in ('start','status','stop'):
            with self.subTest(command=command),patch('loop_work.board_service.'+command,return_value={'status':'running','url':'http://127.0.0.1:1/#private','capability':'private'}) as operation,patch('loop_work.desktop.open_app') as native,contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(self.common+['board',command]),0)
            native.assert_not_called();self.assertNotIn('private',output.getvalue());self.assertNotIn('open_browser',operation.call_args.kwargs)
    def test_linux_open_is_honest_and_has_no_browser_fallback(self):
        with patch('loop_work.desktop.sys.platform','linux'),contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertNotEqual(self.run_cli(['board','open']),0)
        self.assertIn('macOS',error.getvalue());self.assertNotIn('--web',error.getvalue())
