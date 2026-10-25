"""Explicit check scheduling policy is validated without mutating legacy contracts."""
import copy
import unittest
from loop_work.contract import template, validate
from support import ProjectTest

class CheckPolicyContractTests(ProjectTest):
    def test_new_template_defaults_to_fail_fast(self):
        self.assertEqual(template('new-goal','New task','codex')['execution']['check_failure_policy'],'fail_fast')
    def test_validator_accepts_only_supported_policy_values(self):
        _,contract,discovery=self.engine.load()
        for value in ('fail_fast','diagnostic_continue'):
            candidate=copy.deepcopy(contract);candidate['execution']['check_failure_policy']=value
            self.assertFalse(any('check_failure_policy' in e for e in validate(candidate,discovery,self.root)))
        for value in (None,True,1,'continue','',[],{}):
            candidate=copy.deepcopy(contract);candidate['execution']['check_failure_policy']=value
            self.assertTrue(any('check_failure_policy' in e for e in validate(candidate,discovery,self.root)),repr(value))
    def test_legacy_validation_does_not_insert_policy(self):
        _,contract,discovery=self.engine.load();contract['execution'].pop('check_failure_policy',None)
        before=copy.deepcopy(contract)
        self.assertEqual(validate(contract,discovery,self.root),[])
        self.assertEqual(contract,before)
