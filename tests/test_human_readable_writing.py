"""Knowledge prose is readable without losing literal inputs or authority limits."""
from __future__ import annotations

import copy
import json
import unittest

from loop_work.storage import LoopError
from loop_work.writing import record_document, task_document, topic_document, topic_text


class HumanReadableWritingTests(unittest.TestCase):
    def topic(self, **overrides):
        return dict(id='long-machine-topic-id', title='회고 개선 검증', summary='단일 회귀는 통과했지만 일반적인 개선 효과는 아직 입증하지 않았다.',
                    why='다음 작업에서 검증 범위를 구분해 재사용한다.', details=['실제 단일 회귀에서 수정 전 실패와 수정 후 통과를 확인했다.'],
                    scope='project', kind='finding', status='hypothesis', uncertainty='다른 작업에서 같은 효과가 나는지는 미검증이다.',
                    evidence=['docs/회고.md:12'], recorded_at='2026-10-25T01:00:00+09:00', **overrides)

    def test_topic_reading_order_and_full_conclusion_preserve_evidence_and_hypothesis(self):
        value = self.topic()
        original = copy.deepcopy(value)
        rendered = topic_document(value, language='ko')
        headings = ['# 회고 개선 검증', '## 결론', '## 활용 목적', '## 확인한 내용', '## 적용 범위와 한계', '## 근거']
        self.assertEqual([rendered.index(h) for h in headings], sorted(rendered.index(h) for h in headings))
        self.assertIn(value['summary'], rendered)
        self.assertIn('효과가 검증됐다는 뜻이 아닙니다', rendered)
        self.assertIn(value['evidence'][0], rendered)
        self.assertNotIn(value['id'], rendered.partition('<details>')[0])
        self.assertIn(value['id']+'.json', rendered.partition('<details>')[2])
        self.assertEqual(value, original)

    def test_unavailable_title_is_only_a_display_excerpt_and_summary_stays_complete(self):
        value = self.topic()
        del value['title']
        value['summary'] = '관측한 결과와 범위 및 남은 한계를 다음 작업에서도 정확하게 구분하여 재사용할 수 있도록 실제 근거를 함께 남긴다.'
        rendered = topic_document(value, language='ko')
        heading = rendered.splitlines()[0]
        self.assertTrue(heading.endswith('…'))
        self.assertLessEqual(len(heading), 50)
        self.assertIn('\n'+value['summary']+'\n', rendered)
        self.assertNotIn('title', value)

    def test_title_validation_does_not_promote_or_rewrite_record(self):
        value = self.topic()
        topic_text(value)
        for invalid in ('', '제목\n다음 줄', '제목\r다음 줄', '제' * 61, 'TODO'):
            with self.subTest(title=invalid), self.assertRaises(LoopError):
                topic_text({**value,'title':invalid})
        without_title = {k:v for k,v in value.items() if k!='title'}
        topic_text(without_title)
        self.assertEqual(without_title['status'], 'hypothesis')

    def test_completed_task_hides_machine_next_action_and_keeps_stale_result_warning(self):
        value = dict(id='task-id', title='현재 결과 확인', kind='document', phase='completed',
                     goal={'outcome':'실제 변경을 설명한다.'}, result={'summary':'문서를 작성했다.', 'evidence_current':False},
                     next_action='Report the persisted result and do not start another goal.')
        rendered = task_document(value, language='ko')
        self.assertNotIn(value['next_action'], rendered)
        self.assertNotIn('## 다음 행동', rendered)
        self.assertIn('새 검증 전에는 현재 완료로 사용하지 마세요', rendered)
        self.assertIn(value['result']['summary'], rendered)
        self.assertIn('기록된 완료 시점', rendered)
        value['phase'] = 'blocked';value['next_action']='현재 원본 근거를 확인하세요.';value['reason']='검증 환경을 확인해야 한다.'
        rendered = task_document(value, language='ko')
        self.assertIn(value['reason'], rendered);self.assertIn(value['next_action'], rendered)

    def test_human_request_shows_all_choices_and_multiline_response_with_exact_folded_json(self):
        value = dict(id='human-id', title='사용자 확인', kind='decision', status='answered',
                     question='첫째 줄\n\n둘째 줄 ``` <script>원문</script>', options=['선택 '+str(i) for i in range(12)],
                     response={'decision':'answer','text':'첫 답변\n둘째 답변 </details> ```'},
                     execution=None, action=None, task_id='task-id', evidence=[])
        original = copy.deepcopy(value)
        rendered = record_document(value,'human-request')
        visible, _, folded = rendered.partition('<details>')
        for index, option in enumerate(value['options'], 1):
            self.assertIn(str(index)+'. '+option, visible)
        self.assertIn('첫째 줄  \n  \n둘째 줄', visible)
        self.assertIn('첫 답변  \n둘째 답변', visible)
        self.assertNotIn('<script>', visible);self.assertNotIn('</details>', visible)
        self.assertIn('승인·완료 권한을 부여하지 않습니다', visible)
        code = folded.split('```json\n',1)[1].split('\n```',1)[0]
        self.assertEqual(json.loads(code), value)
        self.assertEqual(value, original)
        self.assertEqual(rendered.count('\n```'), 2)

    def test_response_does_not_claim_execution_and_other_record_kinds_keep_scope(self):
        request = dict(id='request',title='작업 재개 검토',status='answered',kind='approval',question='재개할까요?',options=[],
                       action='resume_task',response={'decision':'approve','text':'이 작업만 재개합니다.'},execution=None)
        rendered = record_document(request,'human-request')
        self.assertIn('응답과 실행은 별도 단계', rendered)
        feedback = dict(id='feedback',summary='현재 작업의 범위를 제한한다.',applies_to='이 작업의 API 수정',basis='user',
                        original_input_ref='conversation:message-1',original_input={'original_text':'API 원문\n두 번째 줄'},kind='constraint')
        rendered = record_document(feedback,'feedback')
        self.assertIn('이 작업의 API 수정', rendered);self.assertIn('API 원문  \n두 번째 줄', rendered)
        for kind,value,expected in [('team',dict(id='team',status='done',members={'검토':{'status':'done','summary':'검토했다.'}}),'상위 목표의 완료'),
                                     ('retirement',dict(id='retired',status='retired_obligation',assignment_id='old-unit',replacements=['new-unit'],receipt_ref='/receipt.json'),'실패 이력과 사용한 예산')]:
            with self.subTest(kind=kind):
                self.assertIn(expected,record_document(value,kind))
