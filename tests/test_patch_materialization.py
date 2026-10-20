import copy
import tempfile
from pathlib import Path
import unittest
from loop_work.patches import bytes_pin, materialize_patch
from loop_work.storage import LoopError, file_hash


class PatchTests(unittest.TestCase):
    def patch(self, original, expected, edits):
        return {'path':'example.txt','operation':'patch','base_hash':bytes_pin(original),'result_hash':bytes_pin(expected),'edits':edits}

    def test_exact_multibyte_edit_preserves_unrelated_bytes_and_pin(self):
        original='앞\nkeep\n뒤\n'.encode();expected='앞\nKEPT\n뒤\n'.encode()
        change=self.patch(original,expected,[{'start':4,'end':8,'content':'KEPT'}])
        self.assertEqual(materialize_patch(change,original).encode(),expected)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_bytes(original)
            self.assertEqual(bytes_pin(original),file_hash(p))
            p.chmod(0o700);self.assertEqual(bytes_pin(original,True),file_hash(p))

    def test_rejects_stale_mode_result_overlap_and_utf8_split(self):
        original='가abc'.encode();change=self.patch(original,b'Xabc',[{'start':0,'end':3,'content':'X'}])
        with self.assertRaises(LoopError):materialize_patch(change,original,True)
        with self.assertRaises(LoopError):materialize_patch(change,original+b'!')
        bad=copy.deepcopy(change);bad['result_hash']='0'*64
        with self.assertRaises(LoopError):materialize_patch(bad,original)
        for edits in [[{'start':1,'end':3,'content':'X'}],[{'start':0,'end':3,'content':'X'},{'start':0,'end':0,'content':'Y'}]]:
            bad=copy.deepcopy(change);bad['edits']=edits
            with self.assertRaises(LoopError):materialize_patch(bad,original)
