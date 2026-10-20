from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work import runtime
from loop_work.storage import LoopError, engine_digest, file_hash


class RuntimeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.destination = self.base / 'fixed'

    def test_copy_has_same_engine_pins_and_runs_without_original_source(self):
        expected = engine_digest()
        result = runtime.snapshot(self.destination, expected)
        self.assertEqual(result['engine_digest'], expected)
        manifest = json.loads(Path(result['manifest']).read_text())
        self.assertEqual(set(manifest['files']), set(runtime._inventory()))
        for name, pin in manifest['files'].items():
            self.assertEqual(file_hash(self.destination / name), pin)
        process = subprocess.run([sys.executable, '-B', result['entrypoint'], '--help'],
                                 cwd=self.base, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn('goal setting', process.stdout)
        self.assertFalse((self.destination / '.loop').exists())
        self.assertFalse((self.destination / 'scripts/install.py').exists())

    def test_copied_runtime_isolated_from_later_source_changes(self):
        first = runtime.snapshot(self.destination)
        copied_source = self.destination
        second = self.base / 'second'
        code = ('from pathlib import Path; from loop_work.runtime import snapshot; '
                'import json,sys; print(json.dumps(snapshot(Path(sys.argv[1]))))')
        process = subprocess.run([sys.executable, '-B', '-c', code, str(second)], cwd=copied_source,
                                 capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        pin = file_hash(second / 'rules/work.md')
        (copied_source / 'rules/work.md').write_text('Changed source after the copy\n')
        self.assertEqual(file_hash(second / 'rules/work.md'), pin)
        subprocess_result = subprocess.run([sys.executable, '-B', '-c',
            'from loop_work.storage import engine_digest; print(engine_digest())'],
            cwd=second, capture_output=True, text=True)
        self.assertEqual(subprocess_result.stdout.strip(), first['engine_digest'])

    def test_wrong_expected_digest_and_existing_destination_are_preserved(self):
        with self.assertRaisesRegex(LoopError, 'expected engine digest'):
            runtime.snapshot(self.destination, '0' * 64)
        self.assertFalse(self.destination.exists())
        self.destination.mkdir()
        marker = self.destination / 'user-data'
        marker.write_text('preserve')
        with self.assertRaisesRegex(LoopError, 'already exists'):
            runtime.snapshot(self.destination)
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertEqual(list(self.destination.iterdir()), [marker])

    def test_symlink_destination_parent_and_source_are_rejected(self):
        target = self.base / 'real'
        target.mkdir()
        link = self.base / 'alias'
        link.symlink_to(target, target_is_directory=True)
        for path in (link, link / 'nested'):
            with self.assertRaises(LoopError):
                runtime.snapshot(path)
        self.assertEqual(list(target.iterdir()), [])
        first = runtime.snapshot(self.destination)
        copied_file = self.destination / 'rules/work.md'
        copied_file.unlink()
        copied_file.symlink_to(runtime.SOURCE / 'rules/work.md')
        process = subprocess.run([sys.executable, '-B', str(self.destination / 'scripts/runtime.py'),
                                  'snapshot', '--destination', str(self.base / 'symlink-copy')],
                                 cwd=self.base, capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn('non-symlink', process.stderr)
        self.assertFalse((self.base / 'symlink-copy').exists())

    def test_copy_tampering_and_source_drift_cannot_publish(self):
        original = runtime._copy_files
        def tamper(source, destination, pins):
            original(source, destination, pins)
            (destination / 'rules/work.md').write_text('tampered\n')
        with patch.object(runtime, '_copy_files', side_effect=tamper):
            with self.assertRaisesRegex(LoopError, 'pin mismatch'):
                runtime.snapshot(self.destination)
        self.assertFalse(self.destination.exists())
        pins = runtime._inventory()
        changed = dict(pins, **{'rules/work.md': 'changed'})
        with patch.object(runtime, '_inventory', side_effect=[pins, changed]):
            with self.assertRaisesRegex(LoopError, 'source changed during snapshot'):
                runtime.snapshot(self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.base.iterdir()), [])

    def test_destination_created_during_verification_is_not_replaced(self):
        original = runtime._verify_copy
        def race(directory, pins, expected):
            original(directory, pins, expected)
            self.destination.mkdir()
            (self.destination / 'user-data').write_text('preserve')
        with patch.object(runtime, '_verify_copy', side_effect=race):
            with self.assertRaisesRegex(LoopError, 'appeared during snapshot'):
                runtime.snapshot(self.destination)
        self.assertEqual((self.destination / 'user-data').read_text(), 'preserve')
        self.assertEqual(len(list(self.destination.iterdir())), 1)

    def test_executable_mode_is_preserved_and_mode_tamper_is_rejected(self):
        result = runtime.snapshot(self.destination)
        manifest = json.loads(Path(result['manifest']).read_text())
        target = self.destination / 'scripts/loop.py'
        self.assertEqual(bool(target.stat().st_mode & 0o111),
                         bool((runtime.SOURCE / 'scripts/loop.py').stat().st_mode & 0o111))
        target.chmod(target.stat().st_mode ^ 0o100)
        with self.assertRaisesRegex(LoopError, 'pin mismatch'):
            runtime._verify_copy(self.destination, manifest['files'], result['engine_digest'])

    def test_standalone_cli_rejects_relative_destination(self):
        process = subprocess.run([sys.executable, '-B', str(runtime.SOURCE / 'scripts/runtime.py'),
                                  'snapshot', '--destination', 'relative'],
                                 cwd=self.base, capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertIn('absolute', process.stderr)
        self.assertEqual(list(self.base.iterdir()), [])
