"""Portable board payloads are sealed and usable outside the source checkout."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work import benchmark, runtime, storage
from scripts import install as installer


SOURCE = Path(__file__).resolve().parents[1]
PAYLOADS = ('loop_work/board.py', 'loop_work/board_ui.py', 'rules/board.md',
            'loop_work/board_ui_assets/index.html', 'loop_work/board_ui_assets/app.js',
            'loop_work/board_ui_assets/style.css')


class BoardInstallationTests(unittest.TestCase):
    def test_copied_project_and_runtime_include_board_without_global_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            project = base / 'project'
            project.mkdir()
            # Low-level installs remain portable and must not invoke app setup.
            with patch('scripts.setup_workspace.bootstrap', side_effect=AssertionError('global setup')):
                installer.install(project)
                result = runtime.snapshot(base / 'runtime')
            source_files = benchmark.source_snapshot(SOURCE)['files']
            for name in PAYLOADS:
                self.assertIn(name, source_files)
                self.assertEqual((project / '.loop' / name).read_bytes(), (SOURCE / name).read_bytes())
                self.assertEqual((base / 'runtime' / name).read_bytes(), (SOURCE / name).read_bytes())
            self.assertEqual(result['engine_digest'], storage.engine_digest())
            entrypoints = [project / p / 'skills/loop-work/loop.py' for p in ('.agents', '.claude')]
            entrypoints.append(base / 'runtime/skills/loop-work/loop.py')
            for entrypoint in entrypoints:
                process = subprocess.run([sys.executable, '-B', str(entrypoint), 'board', 'serve', '--help'],
                                         cwd=base, capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn('--no-open', process.stdout)
                self.assertFalse((entrypoint.parent / '../loop-board').resolve().exists())
            self.assertFalse((base / '.loop-work').exists())

    def test_board_assets_are_required_by_seal_and_copy_inventory(self):
        pins = runtime._inventory()
        assets = [name for name in PAYLOADS if 'board_ui_assets/' in name]
        self.assertTrue(all(name in pins for name in assets))
        self.assertEqual(runtime._sealed_engine(pins), storage.engine_digest())
        changed = dict(pins)
        changed[assets[0]] = '0' * 64
        self.assertNotEqual(runtime._sealed_engine(changed), storage.engine_digest())

    def test_symlink_board_asset_is_rejected_by_low_level_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            # Model an invalid source asset without editing the shared source.
            original = Path.is_symlink
            target = SOURCE / 'loop_work/board_ui_assets/app.js'
            with patch.object(Path, 'is_symlink', lambda path: path == target or original(path)):
                with self.assertRaisesRegex(storage.LoopError, 'local UI asset'):
                    installer.managed_files()
