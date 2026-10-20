from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

from loop_work import benchmark


class RuntimeSourceSealTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()

    def minimal_source(self):
        root = self.base / 'source'
        for name in ('scripts/install.py', 'scripts/loop.py', 'rules/work.md', 'loop_work/engine.py'):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# legacy fixture\n')
        return root

    def test_workspace_setup_and_make_install_changes_are_fingerprinted(self):
        root = self.minimal_source()
        setup = root / 'scripts/setup_workspace.py'; setup.write_text('# setup version one\n')
        makefile = root / 'Makefile'; makefile.write_text('install:\n\tpython3 scripts/setup_workspace.py\n')
        before = benchmark.source_snapshot(root)
        self.assertIn('Makefile', before['files'])
        self.assertIn('scripts/setup_workspace.py', before['files'])
        makefile.write_text(makefile.read_text() + '# installation behavior changed\n')
        self.assertNotEqual(before['hash'], benchmark.source_snapshot(root)['hash'])
        before = benchmark.source_snapshot(root)
        setup.write_text('# setup version two\n')
        self.assertNotEqual(before['hash'], benchmark.source_snapshot(root)['hash'])

    def test_runtime_entrypoint_changes_are_included_in_source_identity(self):
        root = self.minimal_source()
        script = root / 'scripts/runtime.py'
        script.write_text('# runtime entrypoint v1\n')
        before = benchmark.source_snapshot(root)
        self.assertEqual(before['files']['scripts/runtime.py'], script.read_text())
        script.write_text('# runtime entrypoint v2\n')
        after = benchmark.source_snapshot(root)
        self.assertNotEqual(before['hash'], after['hash'])

    def test_historical_source_without_runtime_entrypoint_remains_readable(self):
        before = benchmark.source_snapshot(self.minimal_source())
        self.assertNotIn('scripts/runtime.py', before['files'])

    def test_exported_current_source_can_create_runtime_snapshot(self):
        source = Path(__file__).resolve().parents[1]
        snapshot = benchmark.source_snapshot(source)
        exported = self.base / 'exported-source'
        benchmark.export_files(exported, snapshot['files'])
        runtime = self.base / 'task-runtime'
        result = subprocess.run([sys.executable, '-B', str(exported / 'scripts/runtime.py'),
                                 'snapshot', '--destination', str(runtime)],
                                cwd=self.base, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(Path(value['entrypoint']), runtime / 'scripts/loop.py')
        self.assertTrue((runtime / 'scripts/runtime.py').is_file())
        self.assertEqual((runtime / 'scripts/runtime.py').read_text(), snapshot['files']['scripts/runtime.py'])
