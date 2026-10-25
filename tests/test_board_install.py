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
PAYLOADS = ('loop_work/board.py', 'loop_work/board_ui.py', 'loop_work/human_ui.py', 'rules/board.md')


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
                process = subprocess.run([sys.executable, '-B', str(entrypoint), 'board', 'open', '--help'],
                                         cwd=base, capture_output=True, text=True, timeout=20)
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn('--project', process.stdout)
                self.assertNotIn('--no-open', process.stdout)
                self.assertNotIn('--web', process.stdout)
                self.assertFalse((entrypoint.parent / '../loop-board').resolve().exists())
            self.assertFalse((base / '.loop-work').exists())

    def test_api_modules_are_required_by_seal_and_copy_inventory(self):
        pins = runtime._inventory()
        modules = [name for name in PAYLOADS if name.startswith('loop_work/')]
        self.assertTrue(all(name in pins for name in modules))
        self.assertFalse(any('board_ui_assets/' in name for name in pins))
        self.assertEqual(runtime._sealed_engine(pins), storage.engine_digest())
        changed = dict(pins); changed[modules[0]] = '0' * 64
        self.assertNotEqual(runtime._sealed_engine(changed), storage.engine_digest())

    def test_retired_html_is_not_in_managed_payload(self):
        self.assertFalse(any('board_ui_assets/' in name for name in installer.managed_files()))

    def legacy_board_install(self, base):
        import json
        project=base/'project';project.mkdir();installer.install(project)
        manifest_path=project/'.loop/install.json';manifest=json.loads(manifest_path.read_text())
        for name in ('index.html','app.js','style.css','editor.js','markdown.js'):
            relative='.loop/loop_work/board_ui_assets/'+name;path=project/relative;path.parent.mkdir(exist_ok=True);path.write_text('historical '+name)
            manifest['files'][relative]=storage.file_hash(path)
        manifest_path.write_text(json.dumps(manifest));return project

    def test_upgrade_retires_exact_owned_vanilla_files_but_preserves_user_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project=self.legacy_board_install(Path(temporary).resolve())
            folder=project/'.loop/loop_work/board_ui_assets';note=folder/'user-note.md';note.write_text('보존')
            installer.install(project)
            self.assertEqual(note.read_text(),'보존')
            for name in ('index.html','app.js','style.css','editor.js','markdown.js'):self.assertFalse((folder/name).exists())

    def test_modified_owned_vanilla_file_blocks_upgrade_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            project=self.legacy_board_install(Path(temporary).resolve());path=project/'.loop/loop_work/board_ui_assets/editor.js';path.write_text('사용자 변경')
            manifest=project/'.loop/install.json';before=manifest.read_bytes()
            with self.assertRaises(storage.LoopError):installer.install(project)
            self.assertEqual(path.read_text(),'사용자 변경');self.assertEqual(manifest.read_bytes(),before)
