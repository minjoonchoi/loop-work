import copy
import unittest
from loop_work.routing import retry_availability, review_demand
from loop_work.storage import LoopError


def policy():
    return {'version': 1, 'requirements': {'low':1,'medium':1,'high':2},'profiles':[
        {'id':'low','provider':'codex','model':'fixed','effort':'low','capability_rank':1,'cost_rank':1},
        {'id':'high','provider':'codex','model':'fixed','effort':'high','capability_rank':2,'cost_rank':2}]}


class RetryAvailabilityTests(unittest.TestCase):
    def availability(self, **kw):
        args=dict(policy=policy(),provider='codex',current_profile_id='low',attempts=1,calls=1,max_calls=6,remaining_seconds=30)
        args.update(kw);return retry_availability(**args)

    def test_all_caps_precede_ceiling(self):
        for overrides,reason in [({'attempts':3},'attempt_cap'),({'calls':6},'call_cap'),({'remaining_seconds':0},'time_budget')]:
            value=self.availability(current_profile_id='high',**overrides)
            self.assertFalse(value['can_escalate']);self.assertFalse(value['can_retry_same_profile']);self.assertEqual(value['stop_reason'],reason)

    def test_legacy_and_actual_worker_quality_escalate(self):
        for origin,strategy in [('unknown',None),('worker_output','escalate')]:
            value=self.availability(origin=origin,strategy=strategy)
            self.assertTrue(value['can_escalate']);self.assertEqual(value['next_profile']['id'],'high')
        self.assertEqual(self.availability(current_profile_id='high')['stop_reason'],'profile_ceiling')

    def test_nonquality_repairs_keep_profile(self):
        for origin,strategy in [('assignment_input','repair_contract_same_profile'),('orchestrator_fixture','repair_contract_same_profile'),('provider_execution','retry_same_profile'),('evidence_staleness','retry_same_profile')]:
            value=self.availability(origin=origin,strategy=strategy)
            self.assertTrue(value['can_retry_same_profile']);self.assertFalse(value['can_escalate']);self.assertEqual(value['next_profile']['id'],'low')
        with self.assertRaises(LoopError):self.availability(origin='orchestrator_fixture',strategy='escalate')

    def test_bad_policy_and_counts_not_ceiling(self):
        with self.assertRaises(LoopError):self.availability(policy={})
        with self.assertRaises(LoopError):self.availability(attempts=True)
        with self.assertRaises(LoopError):self.availability(remaining_seconds=float('nan'))

    def test_review_retains_high_complexity_with_small_scope(self):
        record={'id':'old-reject','request':{'planning':{'complexity':'high','risk':'high','uncertainty':'low'}}}
        value=review_demand(['A'],['single.py'],[record],'contract.json')
        self.assertEqual(value['planning']['complexity'],'high');self.assertEqual(value['planning']['risk'],'high')
        self.assertEqual(value['scope_features']['version'],1)
        self.assertEqual(value,review_demand(['A'],['single.py'],[record],'contract.json'))

    def test_recovery_retains_profile_but_caps_still_take_precedence(self):
        value=self.availability(current_profile_id='high',requires_recovery=True)
        self.assertTrue(value['can_retry_same_profile']);self.assertFalse(value['can_escalate'])
        self.assertTrue(value['requires_recovery']);self.assertEqual(value['next_profile']['id'],'high')
        exhausted=self.availability(requires_recovery=True,attempts=3)
        self.assertEqual(exhausted['stop_reason'],'attempt_cap');self.assertFalse(exhausted['can_retry_same_profile'])
        with self.assertRaises(LoopError):self.availability(current_profile_id='absent',requires_recovery=True)

    def test_review_retains_historical_high_after_revision(self):
        record={'id':'repaired','request':{'planning':{'complexity':'low','risk':'low','uncertainty':'low'}},
                'history':[{'request':{'planning':{'complexity':'high','risk':'high','uncertainty':'high'}}}]}
        result=review_demand(['A'],['single.py'],[record],'contract')
        self.assertTrue(all(result['planning'][key]=='high' for key in ('complexity','risk','uncertainty')))
        self.assertIn('delegation:repaired#/history',result['planning']['evidence'])
