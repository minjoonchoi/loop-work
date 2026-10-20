"""Optional export diagnostics cannot erase committed human action receipts."""
import copy
import json
import unittest
from unittest.mock import patch

import test_board
import test_board_ui
from loop_work.storage import LoopError


class BoardDiagnosticsTests(unittest.TestCase):
    def test_malformed_persisted_status_preserves_database_commits_and_receipts(self):
        shapes=(
            {'records':[], 'errors':None},
            {'records':{}, 'errors':None},
            {'records':{'task/private':None}, 'errors':[]},
            {'records':{'task/private':{'errors':None}}, 'errors':[]},
            {'records':{'task/private':{'source_revision':[]}}, 'errors':[]},
            {'records':{'task/private':{'export_attempt':'one'}}, 'errors':[]},
            {'records':{}, 'errors':[{'private':'not a diagnostic string'}]},
        )
        for malformed in shapes:
            with self.subTest(malformed=malformed):
                fixture=test_board.BoardTests(); fixture.setUp()
                try:
                    status_path=fixture.kb.home/'vault-export-status.json'
                    original_status=status_path.read_bytes()
                    bad=json.dumps(malformed).encode(); status_path.write_bytes(bad)
                    original_task=fixture.kb.get('task',fixture.task['id'])
                    row=fixture.board.show(fixture.request['id'])
                    listing=fixture.board.list(include_closed=True)
                    self.assertTrue(listing['tasks'])
                    self.assertTrue(listing['vault_status']['errors'])
                    response={'decision':'approve','text':'Approve this exact request once.'}
                    answered=fixture.board.respond(row['id'],response,row['record']['revision'],row['revision'])
                    self.assertTrue(answered['action_committed'])
                    self.assertEqual(answered['request']['response']['text'],response['text'])
                    self.assertTrue(answered['vault_status']['errors'])
                    self.assertEqual(status_path.read_bytes(),bad)
                    self.assertEqual(fixture.kb.get('task',fixture.task['id']),original_task)
                    self.assertEqual(fixture.kb.get('human-request',row['id'])['response']['text'],response['text'])
                    with self.assertRaises(LoopError):
                        fixture.board.respond(row['id'],response,row['record']['revision'],row['revision'])
                    # Repair only our isolated malformed diagnostic fixture,
                    # export the committed response, then corrupt it before execute.
                    status_path.write_bytes(original_status); fixture.kb.sync_vault()
                    current=fixture.board.show(row['id'])
                    self.assertTrue(current['writable'],current)
                    before=copy.deepcopy(fixture.kb.get('task',fixture.task['id']))
                    status_path.write_bytes(bad)
                    executed=fixture.board.execute(row['id'],current['record']['revision'],current['revision'])
                    self.assertTrue(executed['action_committed'])
                    self.assertEqual(executed['request']['status'],'executed')
                    self.assertTrue(executed['vault_status']['errors'])
                    self.assertEqual(status_path.read_bytes(),bad)
                    task=fixture.kb.get('task',fixture.task['id'])
                    self.assertEqual(task['phase'],'goal_setting')
                    for key in ('goal','budget'):
                        self.assertEqual(task.get(key),before.get(key))
                    with self.assertRaises(LoopError):
                        fixture.board.execute(row['id'],current['record']['revision'],current['revision'])
                finally:
                    fixture.doCleanups()

    def test_unexpected_optional_status_exception_cannot_suppress_committed_receipt(self):
        fixture=test_board.BoardTests(); fixture.setUp()
        try:
            row=fixture.board.show(fixture.request['id'])
            with patch.object(fixture.kb,'vault_status',side_effect=TypeError('unexpected optional diagnostic')):
                receipt=fixture.board.respond(row['id'],{'decision':'approve','text':'Approved once'},1,row['revision'])
                self.assertTrue(receipt['action_committed'])
                self.assertEqual(receipt['request']['status'],'answered')
                self.assertTrue(receipt['vault_status']['errors'])
                self.assertEqual(fixture.board.sync_status(True)['status'],'withheld')
            self.assertEqual(fixture.kb.get('human-request',row['id'])['status'],'answered')
        finally:
            fixture.doCleanups()

    def test_actual_http_response_keeps_success_receipt_when_status_is_malformed(self):
        fixture=test_board_ui.BoardUiTests(); fixture.setUp()
        try:
            row=fixture.board.show(fixture.request['id'])
            status=fixture.kb.home/'vault-export-status.json'
            bad=b'{"records":[],"errors":null}'; status.write_bytes(bad)
            code,body=fixture.http('GET','/api/board?include_closed=1')
            self.assertEqual(code,200,body)
            code,body=fixture.http('POST','/api/requests/'+row['id']+'/respond',{
                'expected_revision':row['record']['revision'], 'expected_vault_revision':row['revision'],
                'response':{'decision':'approve','text':'The HTTP receipt must be delivered once.'}})
            self.assertEqual(code,200,body)
            receipt=json.loads(body)
            self.assertTrue(receipt['action_committed'])
            self.assertEqual(receipt['request']['status'],'answered')
            self.assertEqual(receipt['vault_status']['status'],'withheld')
            self.assertEqual(status.read_bytes(),bad)
        finally:
            fixture.doCleanups()
