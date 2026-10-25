"""Inventory/cache boundaries and lossless binary snapshot copying."""
from pathlib import Path
import tempfile
import unittest
from loop_work.desktop_sources import paths
from loop_work.benchmark import export_files
from loop_work.storage import LoopError
class DesktopSourceTests(unittest.TestCase):
    def test_source_inventory_excludes_generated_trees_and_refuses_source_links(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'desktop/src').mkdir(parents=True)
            (root/'desktop/src/App.tsx').write_text('원문')
            (root/'desktop/public').mkdir();(root/'desktop/public/state.ts').write_text('export const data=[0,255]')
            for folder in ('node_modules','src-tauri/target','dist','verification/fixture'):
                path=root/'desktop'/folder;path.mkdir(parents=True);(path/'not-source.js').write_text('generated');(path/'fixture.json').write_text('{"private_fixture":true}')
            self.assertEqual({str(p.relative_to(root)) for p in paths(root)},{'desktop/src/App.tsx','desktop/public/state.ts'})
            (root/'desktop/src/link.ts').symlink_to(root/'desktop/src/App.tsx')
            with self.assertRaises(LoopError):paths(root)
    def test_generated_binary_assets_are_not_read_as_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'desktop/src-tauri/icons').mkdir(parents=True)
            (root/'desktop/src-tauri/icons/icon.png').write_bytes(b'\xff\x00')
            (root/'desktop/public').mkdir();(root/'desktop/public/state.riv').write_bytes(b'\xff\x00')
            self.assertEqual(paths(root),[])
