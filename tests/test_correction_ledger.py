import copy
import unittest
from loop_work.corrections import validate_ledger
from loop_work.storage import LoopError


def row(identifier='C1'):
    return {'id':identifier,'criterion_id':'A','origin':'assignment_input','expected':'exact d82cf77d literal',
            'observed':'wrong D82','source_ref':'.ignored/evidence.json','source_hash':'a'*64,
            'validation_owner':'orchestrator','resolution_status':'unresolved','supersedes':[]}


class CorrectionLedgerTests(unittest.TestCase):
    def test_exact_literals_and_reference_do_not_read_or_grant_authority(self):
        value=row();result=validate_ledger([value],[],['A'])
        self.assertEqual(result,[value]);result[0]['expected']='mutated';self.assertNotEqual(result,[value])

    def test_previous_correction_cannot_disappear_or_mutate(self):
        old=row()
        with self.assertRaises(LoopError):validate_ledger([], [old], ['A'])
        changed=copy.deepcopy(old);changed['expected']='new'
        with self.assertRaises(LoopError):validate_ledger([changed],[old],['A'])
        replacement=row('C2');replacement['supersedes']=['C1'];replacement['resolution_status']='resolved'
        with self.assertRaises(LoopError):validate_ledger([replacement],[old],['A'])
        self.assertEqual(validate_ledger([old,replacement],[old],['A']),[old,replacement])

    def test_three_revisions_and_intrinsic_supersession_validation(self):
        old=row();replacement=row('C2');replacement['supersedes']=['C1']
        replacement['resolution_status']='resolved'
        ledger=[old,replacement]
        self.assertEqual(validate_ledger(ledger,[],['A']),ledger)
        self.assertEqual(validate_ledger(ledger,[old],['A']),ledger)
        self.assertEqual(validate_ledger(ledger,ledger,['A']),ledger)
        with self.assertRaises(LoopError):validate_ledger([replacement,old],[],['A'])
        cycle=copy.deepcopy(old);cycle['supersedes']=['C2']
        with self.assertRaises(LoopError):validate_ledger([cycle,replacement],[],['A'])

    def test_supersession_and_digest_guards(self):
        old=row()
        for field,value in [('source_hash','abc'),('criterion_id','unknown'),('supersedes',['absent']),('origin','guessed')]:
            bad=row('C2');bad[field]=value
            with self.assertRaises(LoopError):validate_ledger([bad],[old],['A'])

    def test_prior_rows_cannot_reorder_or_receive_prepended_items(self):
        first=row('C1');second=row('C2');extra=row('C3')
        prior=[first,second]
        for revised in ([second,first],[extra,first,second],[first,extra,second]):
            with self.assertRaisesRegex(LoopError,'append-only prefix'):
                validate_ledger(revised,prior,['A'])
        self.assertEqual(validate_ledger([first,second,extra],prior,['A']),[first,second,extra])
