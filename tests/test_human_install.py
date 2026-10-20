"""Single-skill discovery and strict ownership of retired human adapters."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import install as installer
from loop_work import benchmark, runtime, storage

SOURCE = Path(__file__).resolve().parents[1]


class HumanInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()

    def dual_layout(self, root, scope, source):
        name, files, links = self.layout(root, scope, source)
        # Freeze the exact formerly shipped dual-v2 ownership shape, without
        # making deleted source skills a prerequisite for migration/uninstall.
        for provider, discovery in (('codex', '.agents'), ('claude', '.claude')):
            adapter = name + '/adapters/' + provider + '-human'
            files[adapter + '/SKILL.md'] = b'---\nname: loop-human\n---\nLegacy human desk\n'
            if provider == 'codex':
                files[adapter + '/agents/openai.yaml'] = b'interface:\n  display_name: Legacy human\n'
            links[adapter + '/loop.py'] = '../../loop.py'
            links[discovery + '/skills/loop-human'] = str(root / adapter)
        return name, files, links

    def dual_install(self, target=None):
        self.layout = installer._link_layout
        with patch.object(installer, '_link_layout', self.dual_layout):
            return installer.install_links(self.home if target is None else None, target=target)

    def dual_copy(self, project):
        files = installer.managed_files()
        for discovery in ('.agents', '.claude'):
            for name in ('SKILL.md', 'loop.py'):
                files[f'{discovery}/skills/loop-human/{name}'] = b'Legacy managed human adapter\n'
        files['.agents/skills/loop-human/agents/openai.yaml'] = b'Legacy managed metadata\n'
        with patch.object(installer, 'managed_files', return_value=files):
            installer.install(project)

    def test_dual_v2_upgrade_retires_only_owned_human_resources_and_is_idempotent(self):
        managed = self.dual_install()
        old = json.loads((managed / 'manifest.json').read_text())
        self.assertIn('.agents/skills/loop-human', old['links'])
        note = managed / 'adapters/codex-human/user-note.txt'
        note.write_text('preserve additional user data')
        installer.install_links(self.home)
        first = (managed / 'manifest.json').read_bytes()
        installer.install_links(self.home)
        self.assertEqual(first, (managed / 'manifest.json').read_bytes())
        manifest = json.loads(first)
        self.assertFalse(any('loop-human' in key or '-human/' in key for key in (*manifest['files'], *manifest['links'])))
        for provider in ('.agents', '.claude'):
            self.assertFalse((self.home / provider / 'skills/loop-human').is_symlink())
            self.assertTrue((self.home / provider / 'skills/loop-work').is_symlink())
        self.assertEqual(note.read_text(), 'preserve additional user data')
        installer.uninstall_links(self.home)
        installer.uninstall_links(self.home)
        self.assertEqual(note.read_text(), 'preserve additional user data')

    def test_dual_v2_uninstall_still_removes_only_exact_owned_resources(self):
        managed = self.dual_install()
        note = self.home / '.agents/skills/mine/SKILL.md'
        note.parent.mkdir(parents=True)
        note.write_text('my skill')
        installer.uninstall_links(self.home)
        self.assertFalse((managed / 'manifest.json').exists())
        self.assertEqual(note.read_text(), 'my skill')
        self.assertFalse((self.home / '.agents/skills/loop-human').is_symlink())

    def test_edited_dual_v2_resource_blocks_upgrade_and_uninstall_before_mutation(self):
        managed = self.dual_install()
        manifest = managed / 'manifest.json'
        original = manifest.read_bytes()
        edited = managed / 'adapters/codex-human/SKILL.md'
        edited.write_text('user-edited managed human skill')
        for operation in (lambda: installer.install_links(self.home), lambda: installer.uninstall_links(self.home)):
            with self.assertRaisesRegex(storage.LoopError, 'Local changes'):
                operation()
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(edited.read_text(), 'user-edited managed human skill')
            self.assertTrue((self.home / '.agents/skills/loop-human').is_symlink())

    def test_new_project_discovery_is_single_skill_and_preserves_unowned_human_skill(self):
        project = self.root / 'project'
        project.mkdir()
        for provider in ('.agents', '.claude'):
            note = project / provider / 'skills/loop-human/SKILL.md'
            note.parent.mkdir(parents=True)
            note.write_text('unowned user human skill')
        installer.install_links(target=project)
        installer.install_links(target=project)
        for provider in ('.agents', '.claude'):
            self.assertTrue((project / provider / 'skills/loop-work').is_symlink())
            self.assertFalse((project / provider / 'skills/loop-human').is_symlink())
            self.assertEqual((project / provider / 'skills/loop-human/SKILL.md').read_text(), 'unowned user human skill')
        self.assertFalse(any('loop-human' in name for name in storage.HARNESS_SKILL_FILES))
        installer.uninstall_links(target=project)
        for provider in ('.agents', '.claude'):
            self.assertEqual((project / provider / 'skills/loop-human/SKILL.md').read_text(), 'unowned user human skill')

    def test_owned_dual_copy_upgrade_removes_standalone_skill_and_preserves_user_files(self):
        project = self.root / 'project'
        project.mkdir()
        self.dual_copy(project)
        note = project / '.agents/skills/loop-human/user-note.txt'
        note.write_text('user data')
        installer.install(project)
        for provider in ('.agents', '.claude'):
            self.assertFalse((project / provider / 'skills/loop-human/SKILL.md').exists())
            self.assertFalse((project / provider / 'skills/loop-human/loop.py').exists())
            self.assertTrue((project / provider / 'skills/loop-work/SKILL.md').is_file())
        self.assertEqual(note.read_text(), 'user data')
        manifest = json.loads((project / '.loop/install.json').read_text())
        self.assertFalse(any('loop-human' in name for name in manifest['files']))
        installer.install(project)

    def test_edited_dual_copy_blocks_upgrade_before_any_managed_write(self):
        project = self.root / 'project'
        project.mkdir()
        self.dual_copy(project)
        edited = project / '.claude/skills/loop-human/SKILL.md'
        edited.write_text('user-edited standalone human skill')
        manifest = (project / '.loop/install.json').read_bytes()
        main = (project / '.agents/skills/loop-work/SKILL.md').read_bytes()
        with self.assertRaisesRegex(storage.LoopError, 'Local changes'):
            installer.install(project)
        self.assertEqual((project / '.loop/install.json').read_bytes(), manifest)
        self.assertEqual((project / '.agents/skills/loop-work/SKILL.md').read_bytes(), main)
        self.assertEqual(edited.read_text(), 'user-edited standalone human skill')

    def test_copied_install_and_snapshot_keep_human_cli_assets_without_second_skill(self):
        project = self.root / 'project'
        project.mkdir()
        installer.install(project)
        for provider in ('.agents', '.claude'):
            helper = project / provider / 'skills/loop-work/loop.py'
            result = subprocess.run([sys.executable, '-B', str(helper), 'human', '--help'],
                                    cwd=self.root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('serve', result.stdout)
            self.assertFalse((project / provider / 'skills/loop-human').exists())
        destination = self.root / 'runtime'
        result = runtime.snapshot(destination)
        self.assertEqual(result['engine_digest'], storage.engine_digest())
        expected = benchmark.source_snapshot(SOURCE)['files']
        self.assertFalse(any(name.startswith('skills/loop-human/') for name in expected))
        for name in ('loop_work/human.py', 'loop_work/human_ui.py', 'loop_work/human_ui_assets/index.html',
                     'loop_work/human_ui_assets/app.js', 'loop_work/human_ui_assets/style.css', 'rules/human.md'):
            self.assertIn(name, expected)
            self.assertEqual((destination / name).read_bytes(), (SOURCE / name).read_bytes())
        result = subprocess.run([sys.executable, '-B', str(destination / 'skills/loop-work/loop.py'), 'human', '--help'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((destination / 'skills/loop-human').exists())
        self.assertFalse((destination / '.loop').exists())

    def test_plain_fixtures_reject_legacy_standalone_human_discovery(self):
        from test_benchmark import make_suite
        path = make_suite(self.root / 'suite')
        for provider in ('.agents', '.claude'):
            skill = path.parent / 'fixtures/tiny-a/app' / provider / 'skills/loop-human/SKILL.md'
            skill.parent.mkdir(parents=True)
            skill.write_text('legacy standalone desk')
            with self.assertRaisesRegex(storage.LoopError, 'installation or state'):
                benchmark.load_suite(path)
            skill.unlink()
